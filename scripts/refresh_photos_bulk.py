"""Re-acquire expired Google place-photo URLs across the cached library.

WHY THIS SHAPE
- Google's lh3 place-photo URLs are time-limited tokens. They were frozen at
  scrape time and have since been revoked, so every stored URL 403s. No code
  change can revive them; they must be re-issued by re-running discovery.
- Discovery is keyed by NAME and returns every match, so one query refreshes a
  whole chain at once. Work is therefore deduplicated by name, not by place.
- gosom (local Docker) is used, not SerpAPI: it is free and already proven to
  restore photos. It is slow, which is why this runs detached and resumable.
- place_id is deliberately NOT passed to scout_single: that makes it reuse the
  cached row and skip discovery entirely — a silent no-op for this purpose.

SAFETY
- Idempotent: any place whose thumbnail already returns 200 is skipped, so a
  re-run costs nothing for work already done.
- No reports, no AI planner, no review scraping (max_reviews=0) — this only
  needs the place listing rewritten.
- Never deletes. Discovery may ADD newly seen places; that is additive.
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from placeintel import cache, photos, pipeline

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/140.0 Safari/537.36"}
LOG = "/opt/gmr/app/data/photo-refresh.log"
MAX_QUERIES = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def log(obj):
    line = json.dumps(obj, ensure_ascii=False)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def status(url):
    if not url:
        return "none"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12) as r:
            return r.status
    except Exception as exc:
        return getattr(exc, "code", type(exc).__name__)


def survey():
    """Return {place_id: (name, address, kind, http_status)} for the whole library."""
    conn = cache.connect()
    rows = conn.execute("SELECT place_id, name, address FROM places").fetchall()
    meta = {r["place_id"]: (r["name"], r["address"]) for r in rows}
    th = photos.resolve_place_thumbnails(conn, list(meta))
    conn.close()

    def one(pid):
        t = th.get(pid) or {}
        return pid, t.get("kind"), status(t.get("thumb_url") or t.get("url"))

    with ThreadPoolExecutor(max_workers=12) as ex:
        return {pid: (meta[pid][0], meta[pid][1], kind, st) for pid, kind, st in ex.map(one, list(meta))}


start = time.time()
before = survey()
alive0 = sum(1 for v in before.values() if v[3] == 200)
log({"event": "start", "places": len(before), "alive": alive0,
     "dead_place_kind": sum(1 for v in before.values() if v[3] != 200 and v[2] == "place"),
     "dead_review_kind": sum(1 for v in before.values() if v[3] != 200 and v[2] == "review")})

# Deduplicate by name: one discovery query refreshes every match it returns.
todo, seen = [], set()
for pid, (name, address, kind, st) in before.items():
    if st == 200 or kind != "place" or not name:
        continue
    key = " ".join((name or "").split()).lower()
    if key in seen:
        continue
    seen.add(key)
    near = ", ".join((address or "").split(",")[-2:]).strip() or None
    todo.append((name, near))

log({"event": "plan", "distinct_queries": len(todo), "cap": MAX_QUERIES})

for i, (name, near) in enumerate(todo[:MAX_QUERIES], 1):
    t0 = time.time()
    try:
        pipeline.scout_single(target=name, near=near, refresh=True, use_ai=False,
                              skip_reports=True, max_reviews=0)
        err = None
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    log({"event": "query", "n": i, "of": min(len(todo), MAX_QUERIES),
         "name": name[:50], "elapsed_s": round(time.time() - t0, 1), "error": err})

after = survey()
alive1 = sum(1 for v in after.values() if v[3] == 200)
log({"event": "done", "places": len(after), "alive_before": alive0, "alive_after": alive1,
     "restored": alive1 - alive0, "total_minutes": round((time.time() - start) / 60, 1)})
