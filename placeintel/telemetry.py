"""Sentry wiring and the event scrubber that keeps customer text out of it.

Extracted from server.py to keep that module under the project's 800-line
budget (AGENTS.md). Behaviour is unchanged: server.py re-exports these names,
so existing callers and tests keep working.

The scrubber is allow-list shaped on purpose. An opt-out denylist silently ships
whatever field a future SDK version adds; an allow-list fails toward sending
less than intended, which is the correct direction for telemetry.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from . import __version__, config

log = logging.getLogger(__name__)


_SENTRY_SENSITIVE_FIELDS = {
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "password",
    "passwd",
    "pwd",
    "apikey",
    "accesskey",
    "accesstoken",
    "refreshtoken",
    "token",
    "secret",
    "clientsecret",
    "privatekey",
    "dsn",
}
_SENTRY_FRAME_FIELDS = {
    "filename", "abs_path", "module", "function", "lineno", "colno", "in_app",
    "package", "instruction_addr", "symbol_addr", "platform",
}


def _sentry_field_is_sensitive(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(normalized == field or normalized.endswith(field) for field in _SENTRY_SENSITIVE_FIELDS)


def _scrub_sentry_value(value: Any) -> Any:
    if isinstance(value, str):
        scrubbed = config.redact_secrets(value)
        home = os.path.expanduser("~").rstrip("/")
        if not home:
            return scrubbed
        if scrubbed == home:
            return "~"
        return scrubbed.replace(f"{home}/", "~/")
    if isinstance(value, dict):
        scrubbed = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() == "vars":
                continue
            safe_key = _scrub_sentry_value(key) if isinstance(key, str) else key
            scrubbed[safe_key] = (
                "REDACTED"
                if isinstance(key, str) and _sentry_field_is_sensitive(key)
                else _scrub_sentry_value(item)
            )
        return scrubbed
    if isinstance(value, list):
        return [_scrub_sentry_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_sentry_value(item) for item in value)
    return value


def _sentry_stacktrace(value: Any) -> dict | None:
    if not isinstance(value, dict) or not isinstance(value.get("frames"), list):
        return None
    frames = []
    for frame in value["frames"]:
        if isinstance(frame, dict):
            frames.append({key: frame[key] for key in _SENTRY_FRAME_FIELDS if key in frame})
    return {"frames": frames}


def _sentry_exceptions(value: Any) -> dict | None:
    if not isinstance(value, dict) or not isinstance(value.get("values"), list):
        return None
    exceptions = []
    for exception in value["values"]:
        if not isinstance(exception, dict):
            continue
        safe = {
            key: exception[key]
            for key in ("type", "module", "thread_id")
            if key in exception
        }
        if isinstance(exception.get("mechanism"), dict):
            safe["mechanism"] = {
                key: exception["mechanism"][key]
                for key in ("type", "handled", "synthetic", "exception_id", "parent_id")
                if key in exception["mechanism"]
            }
        stacktrace = _sentry_stacktrace(exception.get("stacktrace"))
        if stacktrace:
            safe["stacktrace"] = stacktrace
        exceptions.append(safe)
    return {"values": exceptions}


def _scrub_sentry_breadcrumb(breadcrumb: dict, hint: dict | None = None) -> dict:
    """Keep breadcrumb routing metadata while dropping messages and data."""
    scrubbed = _scrub_sentry_value(breadcrumb)
    return {
        key: scrubbed[key]
        for key in ("type", "category", "level", "timestamp", "event_id")
        if key in scrubbed
    }


def _scrub_sentry_event(event: dict, hint: dict | None = None) -> dict:
    """Send diagnostic metadata without request bodies or customer-authored text."""
    scrubbed = _scrub_sentry_value(event)
    safe = {
        key: scrubbed[key]
        for key in (
            "event_id", "timestamp", "start_timestamp", "platform", "level", "logger",
            "transaction", "transaction_info", "release", "environment", "dist", "sdk",
            "modules", "type", "measurements",
        )
        if key in scrubbed
    }
    if isinstance(scrubbed.get("request"), dict) and "method" in scrubbed["request"]:
        safe["request"] = {"method": scrubbed["request"]["method"]}
    exceptions = _sentry_exceptions(scrubbed.get("exception"))
    if exceptions:
        safe["exception"] = exceptions
    stacktrace = _sentry_stacktrace(scrubbed.get("stacktrace"))
    if stacktrace:
        safe["stacktrace"] = stacktrace
    if isinstance(scrubbed.get("threads"), dict) and isinstance(
        scrubbed["threads"].get("values"), list
    ):
        threads = []
        for thread in scrubbed["threads"]["values"]:
            if not isinstance(thread, dict):
                continue
            safe_thread = {
                key: thread[key]
                for key in ("id", "crashed", "current")
                if key in thread
            }
            thread_stack = _sentry_stacktrace(thread.get("stacktrace"))
            if thread_stack:
                safe_thread["stacktrace"] = thread_stack
            threads.append(safe_thread)
        safe["threads"] = {"values": threads}
    if isinstance(scrubbed.get("breadcrumbs"), dict) and isinstance(
        scrubbed["breadcrumbs"].get("values"), list
    ):
        safe["breadcrumbs"] = {
            "values": [
                _scrub_sentry_breadcrumb(item)
                for item in scrubbed["breadcrumbs"]["values"]
                if isinstance(item, dict)
            ]
        }
    if isinstance(scrubbed.get("contexts"), dict):
        contexts = {}
        allowed_context_fields = {
            "trace": {"trace_id", "span_id", "parent_span_id", "op", "status", "origin"},
            "runtime": {"name", "version", "build"},
            "os": {"name", "version", "build", "kernel_version", "rooted"},
            "device": {"arch", "family", "model", "brand"},
        }
        for name, fields in allowed_context_fields.items():
            context = scrubbed["contexts"].get(name)
            if isinstance(context, dict):
                contexts[name] = {key: context[key] for key in fields if key in context}
        if contexts:
            safe["contexts"] = contexts
    if isinstance(scrubbed.get("spans"), list):
        span_fields = {
            "trace_id", "span_id", "parent_span_id", "op", "status", "origin",
            "start_timestamp", "timestamp", "same_process_as_parent", "exclusive_time",
        }
        safe["spans"] = [
            {key: span[key] for key in span_fields if key in span}
            for span in scrubbed["spans"]
            if isinstance(span, dict)
        ]
    return safe


def _init_sentry() -> None:
    if not config.SENTRY_DSN:
        return
    try:
        import sentry_sdk
    except ModuleNotFoundError:  # web extra installs it; bare installs stay quiet-capable
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking off")
        return
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENVIRONMENT,
        release=f"placeintel@{__version__}",
        traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=_scrub_sentry_event,
        before_send_transaction=_scrub_sentry_event,
        before_breadcrumb=_scrub_sentry_breadcrumb,
    )
