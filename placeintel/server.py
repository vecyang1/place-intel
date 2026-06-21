"""Web shell over the pipeline. Run:  placeintel-web  (port 9618 by default).

Jobs run in worker threads and persist progress events into SQLite; the page
streams /api/jobs/{id}/events with /api/jobs/{id} polling as fallback.
Single-user local tool — no auth, binds 127.0.0.1 only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, cache, config, doctor, language, photos, pipeline, profiles

log = logging.getLogger(__name__)
app = FastAPI(title="placeintel", version=__version__)

WEB_DIR = config.PROJECT_DIR / "web"
DEFAULT_PORT = int(os.getenv("PLACEINTEL_PORT", "9618"))
MAX_REVIEWS_IN_DETAIL = 500
MAX_PLACES_IN_LIBRARY = 1000  # the library loads all rows for client-side filtering; cap growth


@app.middleware("http")
async def no_cache_web_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Boundary validation: the web UI already clamps these, but the API is the real
# trust boundary (and the documented VPS lane is multi-client). Reject oversized
# or out-of-range input here so a bad request can't drive unbounded scraping or
# provider spend. Limits mirror the front-end clamps.
MAX_REVIEWS_CAP = 5000
MAX_TOP = 8


class ScoutRequest(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    near: str | None = Field(default=None, max_length=200)
    profile: str | None = Field(default=None, max_length=80)
    top: int = Field(default=3, ge=1, le=MAX_TOP)
    max_reviews: int = Field(default=300, ge=1, le=MAX_REVIEWS_CAP)
    report_lang: str | None = Field(default=None, max_length=16)
    language_hint: str | None = Field(default=None, max_length=16)
    refresh: bool = False
    no_ai: bool = False


class ShopRequest(BaseModel):
    target: str = Field(min_length=1, max_length=600)
    place_id: str | None = Field(default=None, max_length=200)
    near: str | None = Field(default=None, max_length=200)
    profile: str | None = Field(default=None, max_length=80)
    max_reviews: int = Field(default=300, ge=1, le=MAX_REVIEWS_CAP)
    report_lang: str | None = Field(default=None, max_length=16)
    language_hint: str | None = Field(default=None, max_length=16)
    refresh: bool = False


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    place_id: str | None = Field(default=None, max_length=200)
    report_lang: str | None = Field(default=None, max_length=16)
    language_hint: str | None = Field(default=None, max_length=16)
    fresh: bool = False  # skip the QA answer cache


class ReviewTranslateRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=200)
    target_lang: str | None = Field(default=None, max_length=16)


class ReportTranslateRequest(BaseModel):
    report_id: int = Field(ge=1)
    target_lang: str | None = Field(default=None, max_length=16)


class SettingsRequest(BaseModel):
    reason_model: str = Field(min_length=1, max_length=120)


class LanguageSettingsRequest(BaseModel):
    ui_language: str | None = None
    default_answer_language: str | None = None
    default_report_language: str | None = None
    translation_target: str | None = None
    evidence_language: str | None = None
    make_default: bool = False


class FavoriteRequest(BaseModel):
    favorite: bool = True
    refresh_enabled: bool | None = None
    refresh_interval_days: int | None = Field(default=None, ge=1, le=365)
    max_reviews: int | None = Field(default=None, ge=1, le=MAX_REVIEWS_CAP)


def _request_payload(req: BaseModel) -> dict:
    return req.model_dump() if hasattr(req, "model_dump") else req.dict()


def _new_job(kind: str, request: dict | None = None) -> tuple[str, callable]:
    job_id = uuid.uuid4().hex[:12]
    conn = cache.connect()
    try:
        cache.create_job(conn, job_id, kind, request or {}, process_id=os.getpid())
    finally:
        conn.close()

    def on_event(event: dict) -> None:
        conn = cache.connect()
        try:
            cache.append_job_event(conn, job_id, event)
        finally:
            conn.close()

    return job_id, on_event


def _finish_job(job_id: str, result=None, error: str | None = None) -> None:
    conn = cache.connect()
    try:
        cache.finish_job(conn, job_id, result=asdict(result) if result is not None else None,
                         error=config.redact_secrets(error))
    finally:
        conn.close()


@app.on_event("startup")
def _interrupt_stale_jobs() -> None:
    conn = cache.connect()
    try:
        count = cache.interrupt_running_jobs(conn, os.getpid())
    finally:
        conn.close()
    if count:
        log.warning("marked %s stale job(s) as interrupted", count)


def _run_scout(job_id: str, req: ScoutRequest, on_event) -> None:
    try:
        result = pipeline.scout(
            query=req.query, location=req.near, profile_name=req.profile,
            top_n=req.top, max_reviews=req.max_reviews, report_lang=req.report_lang,
            refresh=req.refresh, use_ai=not req.no_ai, on_event=on_event,
            language_hint=req.language_hint,
        )
        _finish_job(job_id, result=result)
    except Exception as exc:
        log.exception("scout job %s failed", job_id)
        _finish_job(job_id, error=str(exc))


def _run_shop(job_id: str, req: ShopRequest, on_event) -> None:
    try:
        result = pipeline.scout_single(
            target=req.target, near=req.near, profile_name=req.profile,
            max_reviews=req.max_reviews, report_lang=req.report_lang,
            refresh=req.refresh, on_event=on_event, language_hint=req.language_hint,
            place_id=req.place_id,
        )
        _finish_job(job_id, result=result)
    except Exception as exc:
        log.exception("shop job %s failed", job_id)
        _finish_job(job_id, error=str(exc))


@app.get("/")
def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__PLACEINTEL_VERSION__", __version__))


@app.post("/api/scout")
def start_scout(req: ScoutRequest) -> dict:
    job_id, on_event = _new_job("scout", _request_payload(req))
    threading.Thread(target=_run_scout, args=(job_id, req, on_event), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/shop")
def start_shop(req: ShopRequest) -> dict:
    job_id, on_event = _new_job("shop", _request_payload(req))
    threading.Thread(target=_run_shop, args=(job_id, req, on_event), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    conn = cache.connect()
    try:
        job = cache.get_job(conn, job_id)
    finally:
        conn.close()
    if not job:
        raise HTTPException(404, "unknown job")
    return json.loads(json.dumps(job, default=str))  # snapshot, not live refs


def _sse_event(event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['id']}\ndata: {data}\n\n"


SSE_MAX_POLLS = 1800  # ~30 min at 1s/poll: bounds a job wedged in 'running' so the stream can't loop forever


def _poll_job_events(job_id: str, last_id: int) -> tuple[dict | None, list, int]:
    """One blocking DB poll (run off the event loop via to_thread): returns (job, new events, advanced cursor)."""
    conn = cache.connect()
    try:
        job = cache.get_job(conn, job_id)
        events = cache.job_events_after(conn, job_id, last_id) if job else []
    finally:
        conn.close()
    for event in events:
        last_id = max(last_id, int(event["id"]))
    return job, events, last_id


@app.get("/api/jobs/{job_id}/events")
async def job_events(
    request: Request,
    job_id: str, after: int = 0,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    try:
        cursor = int(last_event_id) if last_event_id is not None else after
    except ValueError:
        cursor = after
    conn = cache.connect()
    try:
        if not cache.get_job(conn, job_id):
            raise HTTPException(404, "unknown job")
    finally:
        conn.close()

    async def stream():
        last_id = cursor
        for _ in range(SSE_MAX_POLLS):
            if await request.is_disconnected():  # tab closed / connection dropped → stop (don't pin a thread for the whole job)
                return
            job, events, last_id = await asyncio.to_thread(_poll_job_events, job_id, last_id)
            for event in events:
                yield _sse_event(event)
            if not job or job["status"] != "running":
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    return pipeline.ask(req.question, place_id=req.place_id,
                        report_lang=req.report_lang, language_hint=req.language_hint,
                        no_cache=req.fresh)


@app.post("/api/reviews/translate")
def translate_review(req: ReviewTranslateRequest) -> dict:
    try:
        target = req.target_lang or language.config_language_status()["translation_target"]
        return pipeline.translate_review(req.review_id, target)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/reports/translate")
def translate_report(req: ReportTranslateRequest) -> dict:
    try:
        target = req.target_lang or language.config_language_status()["translation_target"]
        return pipeline.translate_report(req.report_id, target)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/qa")
def qa_history(place_id: str | None = None, scope: str = "exact") -> JSONResponse:
    conn = cache.connect()
    try:
        if scope == "all" and not place_id:
            rows = cache.recent_qa_all(conn)
        else:
            rows = cache.recent_qa(conn, place_id)
        return JSONResponse([dict(r) for r in rows])
    finally:
        conn.close()


@app.delete("/api/places/{place_id}")
def delete_place(place_id: str) -> dict:
    conn = cache.connect()
    try:
        deleted = cache.delete_place(conn, place_id)
    finally:
        conn.close()
    if not deleted:
        raise HTTPException(404, "unknown place")
    return {"deleted": place_id}


@app.post("/api/places/{place_id}/favorite")
def favorite_place(place_id: str, req: FavoriteRequest) -> dict:
    conn = cache.connect()
    try:
        meta = cache.set_favorite(
            conn, place_id, req.favorite,
            refresh_enabled=req.refresh_enabled,
            refresh_interval_days=req.refresh_interval_days,
            max_reviews=req.max_reviews,
        )
    finally:
        conn.close()
    if meta is None:
        raise HTTPException(404, "unknown place")
    return meta


@app.get("/api/places")
def places() -> JSONResponse:
    conn = cache.connect()
    try:
        rows = conn.execute(
            """SELECT p.place_id, p.name, p.category, p.rating, p.review_count, p.address,
                      p.last_refreshed,
                      COALESCE(f.favorite, 0) AS favorite,
                      COALESCE(f.refresh_enabled, 0) AS refresh_enabled,
                      f.refresh_interval_days, f.max_reviews, f.last_refresh_at,
                      COUNT(DISTINCT r.review_id) AS cached_reviews,
                      COUNT(DISTINCT rep.id) AS report_count,
                      MAX(rep.created_at) AS latest_report_at,
                      (SELECT rr.profile FROM reports rr
                       WHERE rr.place_id = p.place_id
                       ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1)
                       AS latest_report_profile,
                      (SELECT rr.report_lang FROM reports rr
                       WHERE rr.place_id = p.place_id
                       ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1)
                       AS latest_report_lang
               FROM places p
               LEFT JOIN reviews r ON r.place_id = p.place_id
               LEFT JOIN reports rep ON rep.place_id = p.place_id
               LEFT JOIN place_favorites f ON f.place_id = p.place_id
               GROUP BY p.place_id ORDER BY p.last_refreshed DESC
               LIMIT ?""",
            (MAX_PLACES_IN_LIBRARY,),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["favorite"] = bool(item.get("favorite"))
            item["refresh_enabled"] = bool(item.get("refresh_enabled"))
            out.append(item)
        risks = cache.activity_risks(conn, out)  # one review-date scan, not N+1
        thumbs = photos.resolve_place_thumbnails(conn, [it["place_id"] for it in out])  # batched, not per-place N+1
        for item in out:
            item["activity_risk"] = risks.get(item["place_id"])
            item["thumbnail"] = thumbs.get(item["place_id"])
    finally:
        conn.close()
    return JSONResponse(out)


@app.get("/api/places/{place_id}")
def place_detail(place_id: str) -> dict:
    conn = cache.connect()
    try:
        place = cache.get_place(conn, place_id)
        if not place:
            raise HTTPException(404, "unknown place")
        reviews = conn.execute(
            """SELECT review_id, author, rating, text, review_date, owner_response
               FROM reviews WHERE place_id=? ORDER BY review_date DESC LIMIT ?""",
            (place_id, MAX_REVIEWS_IN_DETAIL),
        ).fetchall()
        report = conn.execute(
            """SELECT id, report_md, report_json, profile, model, report_lang, evidence_lang, created_at FROM reports
               WHERE place_id=? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (place_id,),
        ).fetchone()
        place_payload = {k: place[k] for k in (
                "place_id", "name", "category", "address", "phone", "website",
                "hours_json", "rating", "review_count", "maps_url", "last_refreshed")}
        place_payload["activity_risk"] = cache.activity_risk(conn, place_id)
        place_payload.update(cache.favorite_meta(conn, place_id))
        return {
            "place": place_payload,
            "photos": photos.resolve_place_photos(conn, place_id),
            "reviews": [dict(r) for r in reviews],
            "report": ({"id": report["id"], "md": report["report_md"], "json": json.loads(report["report_json"]),
                        "profile": report["profile"], "model": report["model"],
                        "report_lang": report["report_lang"], "evidence_lang": report["evidence_lang"],
                        "created_at": report["created_at"]}
                       if report else None),
        }
    finally:
        conn.close()


@app.get("/api/searches")
def searches() -> JSONResponse:
    conn = cache.connect()
    try:
        rows = conn.execute(
            "SELECT id, query, location, place_ids_json, verdicts_json, source, created_at "
            "FROM searches ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        names = {r["place_id"]: r["name"]
                 for r in conn.execute("SELECT place_id, name FROM places").fetchall()}
        report_counts = {r["place_id"]: r["count"] for r in conn.execute(
            "SELECT place_id, COUNT(*) AS count FROM reports GROUP BY place_id"
        ).fetchall()}
        out = []
        for row in rows:
            ids = json.loads(row["place_ids_json"] or "[]")
            verdicts = json.loads(row["verdicts_json"]) if row["verdicts_json"] else []
            by_id = {v["place_id"]: v for v in verdicts if isinstance(v, dict)}
            out.append({
                "id": row["id"], "query": row["query"], "location": row["location"],
                "source": row["source"], "created_at": row["created_at"],
                "places": [
                    {"place_id": pid, "name": names[pid],
                     "report_count": int(report_counts.get(pid, 0)),
                     "relevant": by_id.get(pid, {}).get("relevant"),  # None = unjudged
                     "reason": by_id.get(pid, {}).get("reason")}
                    for pid in ids if pid in names  # deleted places drop out of history
                ],
            })
        return JSONResponse(out)
    finally:
        conn.close()


@app.get("/api/reports")
def reports() -> JSONResponse:
    conn = cache.connect()
    try:
        rows = conn.execute(
            """SELECT r.id, r.place_id, p.name, r.profile, r.report_lang, r.evidence_lang,
                      r.review_count, r.created_at
               FROM reports r JOIN places p ON p.place_id = r.place_id
               ORDER BY r.created_at DESC LIMIT 100"""
        ).fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        conn.close()


@app.get("/api/reports/{report_id}")
def report_detail(report_id: int) -> dict:
    conn = cache.connect()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown report")
        return {"md": row["report_md"], "json": json.loads(row["report_json"]),
                "profile": row["profile"], "report_lang": row["report_lang"],
                "evidence_lang": row["evidence_lang"], "created_at": row["created_at"]}
    finally:
        conn.close()


@app.get("/api/profiles")
def profile_list() -> list[str]:
    return profiles.list_profiles()


@app.get("/api/meta")
def meta() -> dict:
    """Models + providers in use — UI transparency. No keys."""
    import placeintel
    return {"version": placeintel.__version__, **config.provider_info()}


@app.get("/api/health")
def health() -> dict:
    """Cheap local health: no provider, scraper, Docker, or Chrome calls."""
    return doctor.cheap_health()


@app.get("/api/health/deep")
def health_deep() -> dict:
    """Opt-in diagnostics that may touch providers and local external tools."""
    return doctor.deep_health()


@app.get("/api/config")
def config_status() -> dict:
    """Non-secret runtime settings for the owner System panel."""
    providers = config.provider_info()
    role_map = {
        "reasoning": providers.get("reason", {}),
        "translation": providers.get("translate", {}),
        "embedding": providers.get("embed", {}),
    }

    def feature(info: dict) -> dict:
        provider = info.get("provider") or "未配置"
        available = provider != "未配置"
        return {
            "available": available,
            "provider": provider,
            "model": info.get("model"),
            "next_action": "none" if available else "configure provider credentials for this feature",
        }

    return {
        "version": __version__,
        "settings": {
            "reason_model": config.reason_model(),
            "translation_model": config.translation_model(),
            "ui_language": language.default_language_setting("ui_language"),
            "default_answer_language": language.default_language_setting("default_answer_language"),
            "default_report_language": language.default_language_setting("default_report_language"),
            "translation_target": language.default_language_setting("translation_target"),
            "evidence_language": language.evidence_language(),
            "cache_ttl_days": config.PLACE_TTL_DAYS,
        },
        "language": language.config_language_status(),
        "runtime": {
            "port": DEFAULT_PORT,
            "data_dir": {"configured": True, "path_visible": False},
        },
        "providers": providers,
        "feature_status": {name: feature(info) for name, info in role_map.items()},
        "health": {"cheap_url": "/api/health", "deep_url": "/api/health/deep"},
        "danger_zone": {
            "destructive_changes": False,
            "message": "Destructive cache/restore actions stay in the CLI and require explicit confirmation.",
        },
    }


@app.post("/api/settings/language")
def update_language_settings(req: LanguageSettingsRequest) -> dict:
    if not req.make_default:
        return {"ok": True, "saved": {}, "language": language.config_language_status()}
    try:
        updates = language.validate_language_settings(_request_payload(req))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if updates:
        config.save_settings(updates)
    return {"ok": True, "saved": updates, "language": language.config_language_status()}


@app.get("/api/models")
def models() -> dict:
    """LIVE model list from the reasoning provider — never a baked-in list."""
    current = config.reason_model()
    try:
        available = config.list_reason_models()
    except Exception as exc:  # provider down ≠ broken UI: current model still shown
        log.warning("model list fetch failed: %s", exc)
        return {"current": current, "models": [], "error": str(exc)}
    return {"current": current, "models": available, "error": None}


@app.post("/api/settings")
def update_settings(req: SettingsRequest) -> dict:
    """Switch the reasoning model. Smoke-tested against the live provider
    before persisting — a bad name fails here, not mid-scout."""
    try:
        config.set_reason_model(req.reason_model)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"模型「{req.reason_model}」冒烟测试失败：{exc}")
    return {"ok": True, **config.provider_info()}


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> None:
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=DEFAULT_PORT)


if __name__ == "__main__":
    main()
