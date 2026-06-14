"""Web shell over the pipeline. Run:  placeintel-web  (port 9618 by default).

Jobs run in worker threads and persist progress events into SQLite; the page
streams /api/jobs/{id}/events with /api/jobs/{id} polling as fallback.
Single-user local tool — no auth, binds 127.0.0.1 only.
"""

from __future__ import annotations

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
from pydantic import BaseModel

from . import __version__, cache, config, doctor, pipeline, profiles

log = logging.getLogger(__name__)
app = FastAPI(title="placeintel", version=__version__)

WEB_DIR = config.PROJECT_DIR / "web"
DEFAULT_PORT = int(os.getenv("PLACEINTEL_PORT", "9618"))
MAX_REVIEWS_IN_DETAIL = 500


@app.middleware("http")
async def no_cache_web_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class ScoutRequest(BaseModel):
    query: str
    near: str | None = None
    profile: str | None = None
    top: int = 3
    max_reviews: int = 300
    report_lang: str | None = None
    refresh: bool = False
    no_ai: bool = False


class ShopRequest(BaseModel):
    target: str
    near: str | None = None
    profile: str | None = None
    max_reviews: int = 300
    report_lang: str | None = None
    refresh: bool = False


class AskRequest(BaseModel):
    question: str
    place_id: str | None = None
    report_lang: str = "zh"
    fresh: bool = False  # skip the QA answer cache


class ReviewTranslateRequest(BaseModel):
    review_id: str
    target_lang: str = "zh"


class SettingsRequest(BaseModel):
    reason_model: str


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
        cache.finish_job(conn, job_id, result=asdict(result) if result is not None else None, error=error)
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
            refresh=req.refresh, on_event=on_event,
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


@app.get("/api/jobs/{job_id}/events")
def job_events(
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

    def stream():
        last_id = cursor
        while True:
            conn = cache.connect()
            try:
                job = cache.get_job(conn, job_id)
                if not job:
                    return
                events = cache.job_events_after(conn, job_id, last_id)
            finally:
                conn.close()
            for event in events:
                last_id = max(last_id, int(event["id"]))
                yield _sse_event(event)
            if job["status"] != "running":
                return
            time.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    return pipeline.ask(req.question, place_id=req.place_id,
                        report_lang=req.report_lang, no_cache=req.fresh)


@app.post("/api/reviews/translate")
def translate_review(req: ReviewTranslateRequest) -> dict:
    try:
        return pipeline.translate_review(req.review_id, req.target_lang)
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
    if not cache.delete_place(conn, place_id):
        raise HTTPException(404, "unknown place")
    return {"deleted": place_id}


@app.get("/api/places")
def places() -> JSONResponse:
    conn = cache.connect()
    rows = conn.execute(
        """SELECT p.place_id, p.name, p.category, p.rating, p.review_count, p.address,
                  p.last_refreshed,
                  COUNT(DISTINCT r.review_id) AS cached_reviews,
                  COUNT(DISTINCT rep.id) AS report_count
           FROM places p
           LEFT JOIN reviews r ON r.place_id = p.place_id
           LEFT JOIN reports rep ON rep.place_id = p.place_id
           GROUP BY p.place_id ORDER BY p.last_refreshed DESC"""
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["activity_risk"] = cache.activity_risk(conn, row["place_id"])
        out.append(item)
    return JSONResponse(out)


@app.get("/api/places/{place_id}")
def place_detail(place_id: str) -> dict:
    conn = cache.connect()
    place = cache.get_place(conn, place_id)
    if not place:
        raise HTTPException(404, "unknown place")
    reviews = conn.execute(
        """SELECT review_id, author, rating, text, review_date, owner_response
           FROM reviews WHERE place_id=? ORDER BY review_date DESC LIMIT ?""",
        (place_id, MAX_REVIEWS_IN_DETAIL),
    ).fetchall()
    report = conn.execute(
        """SELECT report_md, report_json, profile, model, created_at FROM reports
           WHERE place_id=? ORDER BY created_at DESC LIMIT 1""",
        (place_id,),
    ).fetchone()
    place_payload = {k: place[k] for k in (
            "place_id", "name", "category", "address", "phone", "website",
            "hours_json", "rating", "review_count", "maps_url", "last_refreshed")}
    place_payload["activity_risk"] = cache.activity_risk(conn, place_id)
    return {
        "place": place_payload,
        "reviews": [dict(r) for r in reviews],
        "report": ({"md": report["report_md"], "json": json.loads(report["report_json"]),
                    "profile": report["profile"], "model": report["model"],
                    "created_at": report["created_at"]}
                   if report else None),
    }


@app.get("/api/searches")
def searches() -> JSONResponse:
    conn = cache.connect()
    rows = conn.execute(
        "SELECT id, query, location, place_ids_json, verdicts_json, source, created_at "
        "FROM searches ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    names = {r["place_id"]: r["name"]
             for r in conn.execute("SELECT place_id, name FROM places").fetchall()}
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
                 "relevant": by_id.get(pid, {}).get("relevant"),  # None = unjudged
                 "reason": by_id.get(pid, {}).get("reason")}
                for pid in ids if pid in names  # deleted places drop out of history
            ],
        })
    return JSONResponse(out)


@app.get("/api/reports")
def reports() -> JSONResponse:
    conn = cache.connect()
    rows = conn.execute(
        """SELECT r.id, r.place_id, p.name, r.profile, r.review_count, r.created_at
           FROM reports r JOIN places p ON p.place_id = r.place_id
           ORDER BY r.created_at DESC LIMIT 100"""
    ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/reports/{report_id}")
def report_detail(report_id: int) -> dict:
    conn = cache.connect()
    row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "unknown report")
    return {"md": row["report_md"], "json": json.loads(row["report_json"]),
            "profile": row["profile"], "created_at": row["created_at"]}


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
