"""placeintel CLI — walk in armed.

  placeintel scout "会安 吉他租赁"            (AI plans the search — any language)
  placeintel shop "Lazy Gecko Cafe" --near "Hoi An"   (one shop, name or Maps URL)
  placeintel ask "哪家有耐心的老师?"
  placeintel plan "<text>"                  (show what the AI would do, no scrape)
  placeintel report <place_id> / list / history / profiles
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from . import __version__, cache, config, doctor, profiles


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _print_event(event: dict) -> None:
    print(f"  [{event['stage']:<7}] {event['msg']}")


def _print_result(result, top_n: int | None = None) -> None:
    print(f"\n=== {result.query}" + (f" @ {result.location}" if result.location else "")
          + f" · profile: {result.profile} · mode: {result.mode} ===\n")
    dropped = {v["place_id"]: v["reason"] for v in result.filtered if not v["relevant"]}
    print(f"{'#':<3}{'★':<6}{'reviews':<9}name")
    for i, p in enumerate(result.places, 1):
        marker = " ◄ deep-dived" if top_n is None or i <= top_n else ""
        print(f"{i:<3}{p['rating'] or '?':<6}{p['review_count'] or '?':<9}{p['name']}{marker}")
    for place_id, reason in dropped.items():
        print(f"   (AI 排除) {place_id[:20]}… — {reason}")
    for rep in result.reports:
        print(f"\n{'=' * 70}\n{rep['md']}\n→ saved: {rep['path']}")
    if result.errors:
        print("\nWARNINGS:", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)


def _json_payload(command: str, data: dict, ok: bool = True, error: dict | None = None) -> dict:
    payload = {"ok": ok, "version": __version__, "command": command, "data": data}
    if error:
        payload["error"] = error
    return payload


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _add_format_arg(parser: argparse.ArgumentParser, *, ndjson: bool = False) -> None:
    choices = ["text", "json"] + (["ndjson"] if ndjson else [])
    parser.add_argument("--format", choices=choices, default="text",
                        help="output format (default: text)")


def _cmd_scout(args: argparse.Namespace) -> int:
    from . import pipeline
    result = pipeline.scout(
        query=args.query, location=args.near, profile_name=args.profile,
        top_n=args.top, max_reviews=args.max_reviews, lang=args.lang,
        report_lang=args.report_lang, force_serpapi=args.force_serpapi,
        refresh=args.refresh, skip_reports=args.no_reports,
        use_ai=not args.no_ai, on_event=_print_event,
    )
    _print_result(result, top_n=args.top)
    return 0 if (result.reports or args.no_reports) else 1


def _cmd_shop(args: argparse.Namespace) -> int:
    from . import pipeline
    result = pipeline.scout_single(
        target=args.target, near=args.near, profile_name=args.profile,
        max_reviews=args.max_reviews, report_lang=args.report_lang,
        force_serpapi=args.force_serpapi, refresh=args.refresh,
        on_event=_print_event,
    )
    _print_result(result)
    return 0 if result.reports else 1


def _cmd_plan(args: argparse.Namespace) -> int:
    from . import planner
    plan = planner.make_plan(args.text, args.near)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    conn = cache.connect()
    rows = conn.execute(
        "SELECT query, location, source, created_at, place_ids_json, verdicts_json FROM searches "
        "ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    names = {
        r["place_id"]: r["name"]
        for r in conn.execute("SELECT place_id, name FROM places").fetchall()
    }
    conn.close()
    if args.format == "json":
        searches = []
        for r in rows:
            place_ids = json.loads(r["place_ids_json"] or "[]")
            verdicts = json.loads(r["verdicts_json"]) if r["verdicts_json"] else []
            verdict_by_id = {v["place_id"]: v for v in verdicts if isinstance(v, dict)}
            searches.append({
                "query": r["query"],
                "location": r["location"],
                "source": r["source"],
                "created_at": r["created_at"],
                "place_ids": place_ids,
                "place_count": len(place_ids),
                "verdicts": verdicts,
                "places": [
                    {
                        "place_id": pid,
                        "name": names.get(pid),
                        "relevant": verdict_by_id.get(pid, {}).get("relevant"),
                        "reason": verdict_by_id.get(pid, {}).get("reason"),
                    }
                    for pid in place_ids
                ],
            })
        _print_json(_json_payload("history", {"searches": searches}))
        return 0
    if not rows:
        print("No searches yet.")
        return 0
    for r in rows:
        when = time.strftime("%m-%d %H:%M", time.localtime(r["created_at"]))
        n = len(json.loads(r["place_ids_json"] or "[]"))
        loc = f" @ {r['location']}" if r["location"] else ""
        print(f"{when}  [{r['source'] or '?':<7}] {r['query']}{loc} → {n} places")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from . import pipeline
    result = pipeline.ask(args.question, place_id=args.place, top_k=args.top_k,
                          report_lang=args.report_lang, no_cache=args.fresh)
    if result.get("cached"):
        when = time.strftime("%m-%d %H:%M", time.localtime(result["created_at"]))
        print(f"(缓存答案 · 来自 {when} 的相同问题 · --fresh 可强制重新推理)\n")
    print(result["answer"])
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    conn = cache.connect()
    if args.format == "json":
        row = cache.latest_report(conn, args.place_id, args.profile)
        if not row:
            conn.close()
            _print_json(_json_payload(
                "report",
                {"report": None},
                ok=False,
                error={
                    "code": "not_found",
                    "message": f"no cached report for {args.place_id}",
                    "recoverable": True,
                    "next_action": "Run placeintel report in text mode or scout/shop first.",
                },
            ))
            return 5
        report = {
            "id": row["id"],
            "place_id": row["place_id"],
            "profile": row["profile"],
            "model": row["model"],
            "json": json.loads(row["report_json"]),
            "md": row["report_md"],
            "review_count": row["review_count"],
            "created_at": row["created_at"],
        }
        conn.close()
        _print_json(_json_payload("report", {
            "report": report
        }))
        return 0
    from . import analyze
    profile = profiles.load_profile(args.profile or "generic")
    _, md = analyze.analyze_place(
        conn, args.place_id, profile, args.report_lang,
        evidence_lang=args.evidence_lang,
        on_progress=lambda m: print(f"  [report ] {m}", file=sys.stderr))
    conn.close()
    print(md)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    conn = cache.connect()
    rows = conn.execute(
        """SELECT p.place_id, p.name, p.rating, p.review_count,
                  COUNT(r.review_id) AS cached, p.address
           FROM places p LEFT JOIN reviews r ON r.place_id = p.place_id
           GROUP BY p.place_id ORDER BY p.last_refreshed DESC"""
    ).fetchall()
    conn.close()
    if args.format == "json":
        _print_json(_json_payload("list", {"places": [dict(r) for r in rows]}))
        return 0
    if not rows:
        print("Cache empty — run: placeintel scout \"<query>\" --near \"<city>\"")
        return 0
    print(f"{'cached':<8}{'★':<6}{'listed':<8}{'place_id':<24}name / address")
    for r in rows:
        print(f"{r['cached']:<8}{r['rating'] or '?':<6}{r['review_count'] or '?':<8}"
              f"{r['place_id'][:22]:<24}{r['name']} — {(r['address'] or '')[:50]}")
    return 0


def _cmd_profiles(args: argparse.Namespace) -> int:
    if args.format == "json":
        items = []
        for name in profiles.list_profiles():
            prof = profiles.load_profile(name)
            items.append({"name": name, "dimensions": list(prof["dimensions"].keys())})
        _print_json(_json_payload("profiles", {"profiles": items}))
        return 0
    for name in profiles.list_profiles():
        prof = profiles.load_profile(name)
        dims = ", ".join(prof["dimensions"].keys())
        print(f"{name:<12} dimensions: {dims}")
    return 0


def _doctor_payload(report: dict) -> dict:
    payload = _json_payload("doctor", report, ok=bool(report.get("ok")))
    if not report.get("ok"):
        payload["error"] = {
            "code": "health_failed",
            "message": "; ".join(report.get("errors") or ["health check failed"]),
            "recoverable": True,
            "next_action": "Fix the failed checks, then rerun placeintel doctor --json.",
        }
    return payload


def _cmd_doctor(args: argparse.Namespace) -> int:
    require = [item.strip() for item in (args.require or "").split(",") if item.strip()]
    report = doctor.cheap_health(live=args.live, require=require)
    if args.json:
        _print_json(_doctor_payload(report))
    else:
        status = "OK" if report["ok"] else "FAILED"
        print(f"placeintel doctor: {status} · {report['version']} · {report['mode']}")
        for check in report["checks"]:
            mark = "✓" if check["ok"] else "✗"
            print(f"  {mark} {check['name']}: {check['message']} ({check['latency_ms']} ms)")
        for warning in report["warnings"]:
            print(f"  ! {warning}", file=sys.stderr)
        for error in report["errors"]:
            print(f"  ✗ {error}", file=sys.stderr)
    return 0 if report["ok"] else 2


def _cmd_model(args: argparse.Namespace) -> int:
    if args.name:
        try:
            config.set_reason_model(args.name)
        except Exception as exc:
            print(f"✗ 模型「{args.name}」冒烟测试失败，未保存：{exc}", file=sys.stderr)
            return 1
        print(f"✓ 推理模型已切换并保存: {config.reason_model()}（CLI 与 Web 共用）")
        return 0
    current = config.reason_model()
    print(f"当前推理模型: {current}")
    if args.list:
        print("\n该提供商实时可用的模型（来自 /models 端点）:")
        try:
            for name in config.list_reason_models():
                marker = "  ← 当前" if name == current else ""
                print(f"  {name}{marker}")
        except Exception as exc:
            print(f"  (列表获取失败: {exc})", file=sys.stderr)
            return 1
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    conn = cache.connect()
    place = cache.get_place(conn, args.place_id)
    if not place:
        conn.close()
        print(f"unknown place_id {args.place_id}", file=sys.stderr)
        return 1
    rows = cache.get_reviews(conn, args.place_id)
    data = {"place": dict(place), "reviews": [dict(r) for r in rows]}
    conn.close()
    if args.format == "json":
        _print_json(_json_payload("export", data))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="placeintel", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scout", help="AI-planned: discover places, scrape reviews, intel reports")
    s.add_argument("query", help="free text in any language — AI decides what to search")
    s.add_argument("--near", help="city/area, e.g. 'Hoi An, Vietnam' (AI can also extract it)")
    s.add_argument("--profile", choices=profiles.list_profiles() + [None], default=None,
                   help="report profile (default: AI-chosen)")
    s.add_argument("--top", type=int, default=3, help="places to deep-dive (default 3)")
    s.add_argument("--max-reviews", type=int, default=300)
    s.add_argument("--lang", default="en", help="scrape language (default: AI-chosen)")
    s.add_argument("--report-lang", default=None, help="default: language you typed in")
    s.add_argument("--force-serpapi", action="store_true")
    s.add_argument("--refresh", action="store_true", help="ignore caches, re-scrape")
    s.add_argument("--no-reports", action="store_true", help="scrape+cache only")
    s.add_argument("--no-ai", action="store_true", help="skip AI planning/filtering")
    s.set_defaults(func=_cmd_scout)

    sh = sub.add_parser("shop", help="single-shop mode: name or Google Maps URL → one report")
    sh.add_argument("target", help="shop name or Google Maps URL")
    sh.add_argument("--near", help="city/area to disambiguate the name")
    sh.add_argument("--profile", choices=profiles.list_profiles() + [None], default=None)
    sh.add_argument("--max-reviews", type=int, default=300)
    sh.add_argument("--report-lang", default=None)
    sh.add_argument("--force-serpapi", action="store_true")
    sh.add_argument("--refresh", action="store_true")
    sh.set_defaults(func=_cmd_shop)

    pl = sub.add_parser("plan", help="debug: show the AI's search plan, don't run it")
    pl.add_argument("text")
    pl.add_argument("--near")
    pl.set_defaults(func=_cmd_plan)

    h = sub.add_parser("history", help="past searches")
    _add_format_arg(h)
    h.set_defaults(func=_cmd_history)

    a = sub.add_parser("ask", help="RAG question over everything cached")
    a.add_argument("question")
    a.add_argument("--place", help="restrict to one place_id")
    a.add_argument("--top-k", type=int, default=20)
    a.add_argument("--report-lang", default="zh")
    a.add_argument("--fresh", action="store_true",
                   help="skip the QA answer cache, always re-reason")
    a.set_defaults(func=_cmd_ask)

    r = sub.add_parser("report", help="(re)generate a report from cached reviews")
    r.add_argument("place_id")
    r.add_argument("--profile", default=None)
    r.add_argument("--report-lang", default="zh")
    r.add_argument("--evidence-lang", choices=["report", "original"], default=None,
                   help="quoted evidence: translated into report language (default) "
                        "or kept verbatim; global default via PLACEINTEL_EVIDENCE_LANG")
    _add_format_arg(r)
    r.set_defaults(func=_cmd_report)

    l = sub.add_parser("list", help="show cached places")
    _add_format_arg(l)
    l.set_defaults(func=_cmd_list)
    pf = sub.add_parser("profiles", help="show report profiles")
    _add_format_arg(pf)
    pf.set_defaults(func=_cmd_profiles)

    d = sub.add_parser("doctor", help="cheap local readiness checks for humans and agents")
    d.add_argument("--json", action="store_true", help="print one machine-readable JSON document")
    d.add_argument("--live", action="store_true",
                   help="reserved for future deep diagnostics; cheap checks still run today")
    d.add_argument("--require", default="",
                   help="comma-separated required checks, e.g. db,data_dir,google,vectorengine")
    d.set_defaults(func=_cmd_doctor)

    m = sub.add_parser("model", help="show / switch the reasoning model (persisted, shared with web)")
    m.add_argument("name", nargs="?", help="model to switch to (smoke-tested before saving)")
    m.add_argument("--list", action="store_true", help="list models LIVE from the provider")
    m.set_defaults(func=_cmd_model)

    e = sub.add_parser("export", help="dump a place + reviews as JSON")
    e.add_argument("place_id")
    _add_format_arg(e)
    e.set_defaults(func=_cmd_export)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    config.ensure_dirs()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
