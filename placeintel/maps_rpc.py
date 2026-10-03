"""Google Maps reviews over the `qv9Egd` batchexecute RPC.

Captured live 2026-08-31 from a real Maps session; see
`docs/superpowers/plans/2026-08-31-review-scraping-throughput.md` (E5–E8) for the
evidence behind every constant here.

WHAT THIS IS NOT: a replacement for the browser. The request needs an
`X-maps-bgkey` BotGuard token that is minted by JS on a real page load, so there
is no cold start without a browser. What it replaces is the *scrolling*: bootstrap
one page, then walk the reviews over plain HTTP. Measured on the reference place
(1,395 reviews): 69.6 s bootstrap + 29.7 s walk = 1,385 reviews, against ~0.47 s
per review through the DOM.

Historical note, because it cost five wrong probes: `/maps/rpc/listugcposts` is
NOT the endpoint. A live capture of a paginating reviews pane shows zero requests
to `/maps/rpc/` of any kind — which is why every hand-built `pb=` variant returned
403 identically from datacenter and residential IPs.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Sequence

RPC_ID = "qv9Egd"

# Measured: 20 is honoured, 25/30/40/50/100/200 all return an EMPTY envelope with
# HTTP 200. The parameter is rejected, not clamped — asking for more yields zero
# reviews and looks like success.
MAX_PAGE_SIZE = 20

# Measured by one-at-a-time ablation against a known-good request. Everything else
# the browser sends (X-Same-Domain, Referer, x-maps-diversion-context-bin) is
# decoration: dropping it still returns all 10 reviews.
REQUIRED_HEADERS = ("Content-Type", "User-Agent", "X-maps-bgkey")

_PAGE_ARG_RE = re.compile(r'\[(\d+),\\"([^"\\]+)\\"\]')
_FEATURE_ID_RE = re.compile(r"0[xX][0-9a-fA-F]+:0[xX][0-9a-fA-F]+")
_FREQ = "f.req="


class MapsRpcError(RuntimeError):
    """The RPC answered, but not with reviews."""


@dataclass(frozen=True)
class Review:
    """One review. Every field is None when the payload did not state it —
    never 0/"" — so a Google field move surfaces as unknown rather than as a
    confident wrong number."""
    review_id: str | None = None
    rating: int | None = None
    text: str | None = None
    author: str | None = None
    author_id: str | None = None
    author_avatar: str | None = None
    relative_date: str | None = None
    timestamp_us: int | None = None
    photos: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewPage:
    reviews: tuple[Review, ...] = ()
    next_cursor: str | None = None
    #: False when the response was a well-formed but EMPTY envelope. That is the
    #: shape every failure takes here — bad bgkey, no cookies, page size over 20 —
    #: and it arrives as HTTP 200 with ~140 bytes. Callers must check this rather
    #: than a status code.
    has_payload: bool = False
    raw_bytes: int = 0


def unwrap(raw: bytes | str, rpc_id: str = RPC_ID) -> Any | None:
    """Decode a batchexecute response into the RPC's payload.

    The stream is `)]}'` followed by repeating `<count>\\n<json>` — but the count
    is not a usable length. Measured: a frame whose header said 36757 was 36,852
    characters and 36,890 bytes, so slicing by it as characters over-runs the
    frame and slicing by it as bytes truncates mid-string. Both produce a parse
    failure that reads like a rejected request. So the counts are skipped and the
    stream is walked with `raw_decode`.
    """
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    body = text[4:] if text.startswith(")]}'") else text
    body = body.lstrip("\n")
    decoder = json.JSONDecoder()
    pos = 0
    frames: list[Any] = []
    while pos < len(body):
        while pos < len(body) and body[pos] in "\r\n \t0123456789":
            pos += 1
        if pos >= len(body):
            break
        try:
            frame, pos = decoder.raw_decode(body, pos)
        except ValueError:
            break
        frames.append(frame)
    for frame in frames:
        for row in frame if isinstance(frame, list) else []:
            if (isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr"
                    and row[1] == rpc_id and isinstance(row[2], str)):
                try:
                    return json.loads(row[2])
                except ValueError:
                    return None
    return None


def _dig(node: Any, *path: int) -> Any:
    for key in path:
        try:
            node = node[key]
        except (IndexError, KeyError, TypeError):
            return None
    return node


def _photos(record: Any) -> tuple[str, ...]:
    urls: list[str] = []
    for entry in _dig(record, 0, 2, 2) or ():
        url = _dig(entry, 1, 6, 0)
        if isinstance(url, str) and url and url not in urls:
            urls.append(url)
    return tuple(urls)


def _review(record: Any) -> Review:
    rating = _dig(record, 0, 2, 0, 0)
    ts = _dig(record, 0, 1, 2)
    return Review(
        review_id=_dig(record, 0, 0),
        rating=rating if isinstance(rating, int) else None,
        text=_dig(record, 0, 2, 15, 0, 0),
        author=_dig(record, 0, 1, 4, 5, 0),
        author_id=_dig(record, 0, 1, 4, 5, 3),
        author_avatar=_dig(record, 0, 1, 4, 5, 1),
        relative_date=_dig(record, 0, 1, 6),
        timestamp_us=ts if isinstance(ts, int) else None,
        photos=_photos(record),
    )


def parse_page(raw: bytes | str) -> ReviewPage:
    """Turn one RPC response into reviews. Never raises on an empty envelope —
    that is a legitimate end-of-pagination as well as the universal failure
    shape, and only the caller knows which it expected."""
    size = len(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    payload = unwrap(raw)
    if not isinstance(payload, list) or len(payload) < 3 or not isinstance(payload[2], list):
        return ReviewPage(has_payload=False, raw_bytes=size)
    cursor = payload[1] if isinstance(payload[1], str) else None
    return ReviewPage(
        reviews=tuple(_review(r) for r in payload[2]),
        next_cursor=cursor,
        has_payload=True,
        raw_bytes=size,
    )


@dataclass(frozen=True)
class MergeReport:
    """What merging the on-screen head into the walk actually produced."""
    head: int = 0
    walked: int = 0
    merged: int = 0
    overlap: int = 0
    head_without_id: int = 0
    start_offset: int | None = None
    #: How many reviews sit between the end of the head and the start of the
    #: walk. `None` when the cursor did not say where the walk began, which is
    #: NOT the same as zero and must not be rendered as a clean merge.
    gap: int | None = None
    verdict: str = "unverified"          # contiguous | gap | unverified


def merge_head(head: Sequence[Review], walked: Sequence[Review], *,
               start_offset: int | None) -> tuple[tuple[Review, ...], MergeReport]:
    """Concatenate the on-screen head with the walked tail, newest first.

    Maps renders the first ~10 review cards from data inlined in the page, so the
    earliest request the page ever makes already carries cursor offset 10 and
    there is no position-0 request to capture. The head is therefore read from
    the DOM and joined here.

    Contiguity is the property that makes the join honest: the head must reach at
    least as far as the walk begins, or reviews exist that are in neither list.
    That is decidable from the cursor and the head's length, so it is returned as
    a verdict rather than assumed — a 7-card head against a walk starting at 10
    silently loses 3 reviews and still looks like a complete run.
    """
    seen: dict[str, int] = {}
    out: list[Review] = []
    head_without_id = 0
    for review in head:
        rid = review.review_id
        if not rid:
            head_without_id += 1
            out.append(review)
            continue
        if rid in seen:
            continue
        seen[rid] = len(out)
        out.append(review)

    overlap = 0
    for review in walked:
        rid = review.review_id
        if rid and rid in seen:
            # Same review from both halves. Keep the WALKED copy — its timestamp
            # is exact, while the head's is derived from a relative string — but
            # at the head's position, which is the one that knows the ordering.
            overlap += 1
            out[seen[rid]] = review
            continue
        if rid:
            seen[rid] = len(out)
        out.append(review)

    # UNIQUE ids, not len(head). The DOM extractor returns one payload per
    # matching ELEMENT and Maps renders two per card, so a 10-card head arrives
    # as 20 rows. Counting those as 20 lets a head that stops at review 10
    # "reach" a walk starting at 15 and report a five-review hole as contiguous —
    # the gate's denominator inflating is the one way it can pass while wrong.
    head_ids = len({r.review_id for r in head if r.review_id})
    if start_offset is None:
        gap, verdict = None, "unverified"
    elif overlap:
        # Sharing a review proves the two halves touch, whatever the cursor said.
        gap, verdict = 0, "contiguous"
    else:
        gap = max(0, start_offset - head_ids)
        verdict = "gap" if gap else "contiguous"

    return tuple(out), MergeReport(
        head=len(head), walked=len(walked), merged=len(out), overlap=overlap,
        head_without_id=head_without_id, start_offset=start_offset,
        gap=gap, verdict=verdict)


def build_body(template: str, *, page_size: int | None = None,
               cursor: str | None = None) -> str:
    """Rewrite `[N,"<cursor>"]` inside a captured `f.req` body.

    Only that one argument is touched; the rest of the body is re-encoded from
    the same decoded string, so no other byte changes meaning by accident.
    """
    if page_size is not None and page_size > MAX_PAGE_SIZE:
        raise ValueError(
            f"page_size {page_size} exceeds MAX_PAGE_SIZE={MAX_PAGE_SIZE}; "
            "larger values are rejected with an empty HTTP 200, not clamped"
        )
    # Rewrite ONLY the f.req field. Splitting on "&" keeps every other field and
    # the trailing separator byte-identical; decoding the whole body instead
    # re-encodes that separator into f.req's value as %26.
    parts = template.split("&")
    for index, part in enumerate(parts):
        if not part.startswith(_FREQ):
            continue
        decoded = urllib.parse.unquote(part[len(_FREQ):])
        match = _PAGE_ARG_RE.search(decoded)
        if not match:
            raise MapsRpcError('no [page_size,"cursor"] argument in f.req')
        size = match.group(1) if page_size is None else page_size
        cur = match.group(2) if cursor is None else cursor
        rewritten = decoded[:match.start()] + f'[{size},\\"{cur}\\"]' + decoded[match.end():]
        parts[index] = _FREQ + urllib.parse.quote(rewritten, safe="")
        return "&".join(parts)
    raise MapsRpcError("no f.req= field in template body")


def cursor_of(template: str) -> str | None:
    for part in template.split("&"):
        if part.startswith(_FREQ):
            match = _PAGE_ARG_RE.search(urllib.parse.unquote(part[len(_FREQ):]))
            return match.group(2) if match else None
    return None


def normalize_feature_id(value: Any) -> str | None:
    """Canonical `0x<hex>:0x<hex>`, or None when *value* is not a feature id.

    Returns None — never the input, never "" — because this feeds an equality
    guard. A normaliser that passes unrecognised text through would make two
    different unparseable strings compare equal, and the guard would agree
    precisely when it understood nothing.
    """
    if not isinstance(value, str):
        return None
    match = _FEATURE_ID_RE.fullmatch(value.strip())
    if not match:
        return None
    left, right = value.strip().split(":", 1)
    return f"0x{int(left, 16):x}:0x{int(right, 16):x}"


def feature_id_in(text: Any) -> str | None:
    """First `0x<hex>:0x<hex>` anywhere in *text*, canonicalised.

    Reads a Maps URL's `ftid=`/`!1s` identity with the same normaliser the
    captured request goes through, so the two sides of the guard cannot disagree
    about formatting rather than about the listing.
    """
    if not isinstance(text, str):
        return None
    match = _FEATURE_ID_RE.search(text)
    return normalize_feature_id(match.group(0)) if match else None


def feature_id_of(template: str) -> str | None:
    """The listing a captured `f.req` is actually asking about.

    This is the whole landed-identity guard: the request names the feature id,
    so a browser that searched its way onto a different shop of a similar name
    says so here, in the bytes it is about to send.
    """
    for part in template.split("&"):
        if not part.startswith(_FREQ):
            continue
        return feature_id_in(urllib.parse.unquote(part[len(_FREQ):]))
    return None


def cursor_offset(cursor: str | None) -> int | None:
    """How far into the review list a cursor starts, or None if it does not say.

    A cursor captured mid-scroll carries an offset, and walking from it skips
    everything before it while still looking like a complete, healthy run.
    """
    if not isinstance(cursor, str) or ":" not in cursor:
        return None
    tail = cursor.rsplit(":", 1)[1]
    return int(tail) if tail.isdigit() else None


def same_feature(left: Any, right: Any) -> bool:
    """True only when both sides name the SAME listing.

    Unknown is not a match. If either side is missing the honest answer is "I
    could not check", and returning True there would make the guard pass exactly
    in the cases it exists to catch.
    """
    a, b = normalize_feature_id(left), normalize_feature_id(right)
    return a is not None and a == b


def missing_headers(headers: Mapping[str, str]) -> tuple[str, ...]:
    lowered = {k.lower() for k in headers}
    return tuple(h for h in REQUIRED_HEADERS if h.lower() not in lowered)


@dataclass
class WalkStats:
    pages: int = 0
    returned: int = 0
    unique: int = 0
    empty_pages: int = 0
    stopped_because: str = ""


def walk(post, template: str, *, page_size: int = MAX_PAGE_SIZE,
         max_reviews: int | None = None, stats: WalkStats | None = None
         ) -> Iterator[Review]:
    """Yield reviews by advancing the cursor. `post(body) -> bytes`.

    Stops on: no next cursor, an empty envelope, `max_reviews`, or a page that
    contributes nothing new. That last guard matters — a cursor that stops
    advancing returns a full, healthy-looking page forever, and without a
    disjointness check that is indistinguishable from working pagination.
    """
    st = stats if stats is not None else WalkStats()
    seen: set[str] = set()
    body = build_body(template, page_size=page_size)
    while True:
        page = parse_page(post(body))
        st.pages += 1
        if not page.has_payload:
            st.empty_pages += 1
            st.stopped_because = "empty envelope (HTTP 200 with no payload)"
            return
        fresh = 0
        for review in page.reviews:
            st.returned += 1
            if review.review_id and review.review_id in seen:
                continue
            if review.review_id:
                seen.add(review.review_id)
            fresh += 1
            st.unique += 1
            yield review
            if max_reviews is not None and st.unique >= max_reviews:
                st.stopped_because = "max_reviews reached"
                return
        if fresh == 0:
            st.stopped_because = "page contributed no new reviews (cursor not advancing)"
            return
        if not page.next_cursor:
            st.stopped_because = "no next cursor — end of reviews"
            return
        body = build_body(template, page_size=page_size, cursor=page.next_cursor)
