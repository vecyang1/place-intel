"""Thin human and agent CLI adapter for private saved-place data."""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from functools import partial
from pathlib import Path

from . import cache, saved_places


def _cmd_saved_import(args, *, json_payload, print_json) -> int:
    conn = cache.connect()
    try:
        try:
            result = saved_places.import_takeout(
                conn,
                Path(args.path),
                limits=saved_places.ImportLimits.from_env(),
                emit_events=args.format == "text",
                source_label=args.source_label,
                adopt_unlabeled=args.adopt_unlabeled,
            )
            states = saved_places.inventory(conn)["states"]
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("saved_import_"):
                code = "saved_import_invalid_input"
            error = {
                "code": code,
                "message": "Saved-place import rejected the input.",
                "recoverable": True,
                "next_action": (
                    "Use an official Google Takeout Saved CSV, Takeout directory, "
                    "or ZIP and retry."
                ),
            }
            if args.format == "json":
                print_json(json_payload("saved-import", {}, ok=False, error=error))
            else:
                print(f"saved import failed: {code}", file=sys.stderr)
            return 1
    finally:
        conn.close()
    raw = asdict(result)
    data = {
        "run_id": raw["run_id"],
        "source_digest": raw["source_digest"],
        "source_label": raw["source_label"],
        "files": raw["file_count"],
        "rows": raw["row_count"],
        "skipped": raw["skipped_rows"],
        "adopted_collections": raw["adopted_collections"],
        "created": {
            "collections": raw["created_collections"],
            "items": raw["created_items"],
            "memberships": raw["created_memberships"],
        },
        "updated": {
            "collections": raw["updated_collections"],
            "items": raw["updated_items"],
            "memberships": raw["updated_memberships"],
        },
        "states": states,
    }
    if args.format == "json":
        print_json(json_payload("saved-import", data))
    else:
        print(
            f"Imported {data['rows']} row(s) from {data['files']} file(s): "
            f"{data['created']['items']} new item(s), "
            f"{data['created']['memberships']} new membership(s)."
        )
    return 0


def _cmd_saved_inventory(args, *, json_payload, print_json) -> int:
    conn = cache.connect()
    try:
        data = saved_places.inventory(
            conn,
            state=args.state,
            collection=args.collection,
            source_label=args.source_label,
            limit=args.limit,
        )
    finally:
        conn.close()
    if args.format == "json":
        print_json(json_payload("saved-inventory", data))
    else:
        totals = data["totals"]
        print(
            f"{totals['items']} saved item(s) across {totals['collections']} collection(s) "
            f"and {totals['memberships']} membership(s)."
        )
        for item in data["collections"]:
            print(f"  {item['memberships']:<6}{item['name']} [{item['source_product']}]")
        if args.state or args.collection:
            print(f"Matched {data['matched_items']} item(s):")
            for item in data["items"]:
                label = item["title"] or item["address"] or item["saved_item_id"]
                print(f"  {label} · {item['state']} · {', '.join(item['collections'])}")
    return 0


def register(subparsers, *, add_format_arg, json_payload, print_json) -> None:
    saved_import = subparsers.add_parser(
        "saved-import",
        help="import a private Google Takeout Saved CSV, directory, or ZIP",
    )
    saved_import.add_argument("path", help="private Takeout CSV, directory, or ZIP")
    saved_import.add_argument(
        "--source-label",
        type=saved_places.normalize_source_label,
        help="opaque local source label; use an alias, never an account email",
    )
    saved_import.add_argument(
        "--adopt-unlabeled",
        action="store_true",
        help="scope a matching prior unlabeled import after source-file hash verification",
    )
    add_format_arg(saved_import)
    saved_import.set_defaults(
        func=partial(
            _cmd_saved_import,
            json_payload=json_payload,
            print_json=print_json,
        )
    )

    saved_inventory = subparsers.add_parser(
        "saved-inventory",
        help="show local saved-place collections, items, memberships, and states",
    )
    saved_inventory.add_argument("--state", choices=saved_places.SAVED_STATES)
    saved_inventory.add_argument("--collection", help="exact saved collection name")
    saved_inventory.add_argument(
        "--source-label",
        type=saved_places.normalize_source_label,
        help="exact opaque source label",
    )
    saved_inventory.add_argument("--limit", type=_bounded_limit, default=100)
    add_format_arg(saved_inventory)
    saved_inventory.set_defaults(
        func=partial(
            _cmd_saved_inventory,
            json_payload=json_payload,
            print_json=print_json,
        )
    )


def _bounded_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 1_000:
        raise argparse.ArgumentTypeError("limit must be between 1 and 1000")
    return parsed
