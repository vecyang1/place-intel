"""Gemini Embedding 2 via VectorEngine: embed review docs/queries, index, search.

Follows the gemini-embedding-2-guide skill conventions:
  - RAG asymmetric prefixes ("title: ... | text: ..." for docs,
    "task: search result | query: ..." for queries).
  - Dimensions below 3072 are NOT pre-normalized by the API, so every vector
    is L2-normalized here before storage/return.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from google import genai
from google.genai import types

from . import cache, config

logger = logging.getLogger(__name__)

MAX_DOC_CHARS = 6000
# VERIFIED 2026-06-11: a plain list-of-strings `contents` gets AGGREGATED into ONE
# vector (both Google official and VectorEngine). True per-item fan-out requires an
# explicit list of types.Content objects — Google official then returns one vector
# per Content (64 in 1.6s). VectorEngine aggregates even those, so a count check
# guards every batch and falls back to per-item calls.
API_BATCH_SIZE = 64
EMBED_WORKERS = 8  # per-item fallback concurrency only
MAX_TRIES = 3
BACKOFF_BASE_SECONDS = 2.0
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
DOC_TITLE_FALLBACK = "review"


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    """Embedding client — Google official preferred (VectorEngine embeds slowly
    and aggregates batched contents; see config.py routing note)."""
    api_key, http_options = config.embed_credentials()
    logger.info("embedding via %s", "VectorEngine" if http_options else "Google official")
    return genai.Client(api_key=api_key, http_options=http_options)


def _is_transient(exc: Exception) -> bool:
    """True for rate limits, server errors, and connection-level failures."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and (code in TRANSIENT_HTTP_CODES or code >= 500):
        return True
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _with_retry(call):
    """Run a zero-arg callable with exponential backoff on transient errors."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            return call()
        except Exception as exc:
            if not _is_transient(exc) or attempt == MAX_TRIES:
                raise
            delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
            logger.warning(
                "Transient embed error (attempt %d/%d), retrying in %.1fs: %s",
                attempt, MAX_TRIES, delay, exc,
            )
            time.sleep(delay)
    raise RuntimeError("unreachable")  # loop always returns or raises


def _embed_one(text: str) -> list[float]:
    """Embed a single text (fallback path for providers that aggregate batches)."""
    response = _with_retry(lambda: _client().models.embed_content(
        model=config.EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=config.EMBED_DIMS),
    ))
    if len(response.embeddings) != 1:
        raise RuntimeError(f"expected 1 embedding, got {len(response.embeddings)}")
    return response.embeddings[0].values


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """One call, one vector per text — requires explicit Content objects."""
    contents = [types.Content(parts=[types.Part.from_text(text=t)]) for t in texts]
    response = _with_retry(lambda: _client().models.embed_content(
        model=config.EMBED_MODEL,
        contents=contents,
        config=types.EmbedContentConfig(output_dimensionality=config.EMBED_DIMS),
    ))
    if len(response.embeddings) != len(texts):
        raise _BatchAggregated(
            f"provider returned {len(response.embeddings)} vectors for {len(texts)} texts"
        )
    return [e.values for e in response.embeddings]


class _BatchAggregated(RuntimeError):
    """Provider collapsed a batch into fewer vectors (VectorEngine behavior)."""


def _embed_many(texts: list[str]) -> list[list[float]]:
    """Order-preserving embedding: batched fan-out, per-item fallback."""
    if len(texts) == 1:
        return [_embed_one(texts[0])]
    try:
        results: list[list[float]] = []
        for start in range(0, len(texts), API_BATCH_SIZE):
            results.extend(_embed_batch(texts[start:start + API_BATCH_SIZE]))
        return results
    except _BatchAggregated as exc:
        logger.warning("batch embedding unavailable (%s); per-item fallback", exc)
    # Pre-warm: concurrent lru_cache misses build duplicate clients and the
    # discarded one closes its transport mid-flight ("client has been closed").
    _client()
    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
        return list(pool.map(_embed_one, texts))


def _l2_normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0.0, 1.0, norms)).astype(np.float32)


def embed_docs(texts: list[str], titles: list[str] | None = None) -> np.ndarray:
    """Embed documents for RAG retrieval. Returns float32 array (n, EMBED_DIMS)."""
    if titles is not None and len(titles) != len(texts):
        raise ValueError(
            f"titles length ({len(titles)}) must match texts length ({len(texts)})"
        )
    if not texts:
        return np.empty((0, config.EMBED_DIMS), dtype=np.float32)
    prefixed = [
        f"title: {(titles[i] if titles else None) or DOC_TITLE_FALLBACK}"
        f" | text: {text[:MAX_DOC_CHARS]}"
        for i, text in enumerate(texts)
    ]
    return _l2_normalize_rows(np.asarray(_embed_many(prefixed), dtype=np.float32))


def embed_query(query: str) -> np.ndarray:
    """Embed a search query. Returns L2-normalized float32 array (EMBED_DIMS,)."""
    vec = np.asarray(_embed_one(f"task: search result | query: {query}"), dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    return (vec / norm).astype(np.float32) if norm else vec


def index_pending(
    conn: sqlite3.Connection, batch_size: int = 32, limit: int = 2000
) -> int:
    """Embed and store vectors for reviews that lack them. Returns count indexed.

    Vectors are persisted after every batch so partial progress survives a crash.
    """
    total = 0
    while True:
        rows = cache.reviews_missing_vectors(conn, limit)
        if not rows:
            break
        logger.info("Indexing %d reviews missing vectors", len(rows))
        for start in range(0, len(rows), batch_size):
            chunk = rows[start:start + batch_size]
            texts = [f"rating {row['rating']}/5 — {row['text']}" for row in chunk]
            matrix = embed_docs(texts, titles=[DOC_TITLE_FALLBACK] * len(chunk))
            pairs = [(row["review_id"], matrix[i]) for i, row in enumerate(chunk)]
            cache.store_vectors(conn, pairs)
            total += len(pairs)
        if len(rows) < limit:
            break
    logger.info("Indexed %d new review vectors", total)
    return total


def search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 20,
    place_id: str | None = None,
) -> list[dict]:
    """Semantic search over cached review vectors."""
    return cache.vector_search(
        conn, embed_query(query), top_k=top_k, place_id=place_id
    )
