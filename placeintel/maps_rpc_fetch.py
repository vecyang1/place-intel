"""Networked side of the qv9Egd reviews RPC: bootstrap a browser, then walk.

`maps_rpc` is pure parsing. This module is the part that touches Chrome and the
network, kept separate so the parser stays testable without either.

Two consistency checks ride the bootstrap, so neither costs a second browser run:

* **Identity** — the captured `f.req` states the feature id it is asking about.
  Compared against the id the caller's Maps URL named, this turns a scrape that
  searched its way onto a different shop from a silent success into a refusal.
  Measured 2026-08-31: a DOM scrape stored 314 reviews that shared 3 of 291
  texts with the page they claimed to come from, and reported `completed`.
* **Parity** — the review ids visible in the DOM of the same session, against the
  first RPC page. Deliberately the weaker gate: sort order and timing legitimately
  shift the window, so only a COMPLETE disjointness with data on both sides is
  treated as evidence.

Selenium is imported lazily: `reviews.py` imports this module in the app venv,
which has no SeleniumBase, and only ever runs :func:`fetch` in the vendor venv.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import maps_rpc

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SCRAPER_DIR = REPO / "vendor" / "google-reviews-scraper-pro"
# Enough passes for the reviews pane to fire at least one paginating request.
# Each is ~1.5 s, and the loop exits as soon as an offset-0 template appears.
MAX_CAPTURE_PASSES = 12


def _env_int(name: str, default: int) -> int:
    """An operator-tunable integer. A malformed value keeps the default rather
    than crashing a scrape at 3am over a typo — and says so."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[maps-rpc] ignoring {name}={raw!r} (not an integer)", file=sys.stderr)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[maps-rpc] ignoring {name}={raw!r} (not a number)", file=sys.stderr)
        return default


# Defaults for the operator-tunable settings below. Each is read through its
# function, NOT captured into a module constant at import: a value frozen at
# import detaches from the environment, and the same mistake in this file (a
# default argument evaluated once) made a timeout test wait out its own child
# instead of timing out. A setting nobody can actually set is not configuration.
HEAD_SAMPLE_DEFAULT = 40
MIN_COVERAGE_DEFAULT = 0.95
HEAD_EXPAND_SETTLE_DEFAULT_S = 1.0


def head_sample() -> int:
    """Ceiling on how many on-screen cards to read as the head. Only a ceiling —
    the page decides how many it renders (~10), and that count is what has to
    reach the walk's start offset."""
    return _env_int("PLACEINTEL_MAPS_RPC_HEAD_SAMPLE", HEAD_SAMPLE_DEFAULT)


def min_coverage() -> float:
    """Fraction of Google's own stated review count the merged result must reach.

    Not 1.0: the stated count and the enumerable reviews legitimately differ a
    little. Below it the run is refused and the slower, complete DOM path takes
    over — which is the whole reason for keeping two paths."""
    return _env_float("PLACEINTEL_MAPS_RPC_MIN_COVERAGE", MIN_COVERAGE_DEFAULT)


def head_expand_settle_s() -> float:
    """How long to let the "More" expansion land before reading the cards back."""
    return _env_float("PLACEINTEL_MAPS_RPC_HEAD_SETTLE_S",
                      HEAD_EXPAND_SETTLE_DEFAULT_S)
PARITY_SAMPLE = 20
# Below this many DOM cards, a disagreement is not evidence. The reviews pane
# renders lazily after a re-sort, and a sample of 3 caught mid-render disagreed
# with a walk that was independently verified correct — so a small sample must
# report "could not check", not "these are different places".
PARITY_MIN_SAMPLE = 5
# How long to let the re-sorted pane populate before sampling it.
PARITY_SETTLE_PASSES = 8


def _noop(_msg: str) -> None:
    pass


def _scraper_dir() -> Path:
    return Path(os.environ.get("PLACEINTEL_SCRAPER_DIR", DEFAULT_SCRAPER_DIR))


_RPCIDS_RE = re.compile(r"[?&]rpcids=([^&]+)")


def _ensure_vendor_importable() -> None:
    """Put the vendored scraper on `sys.path`, once.

    Both the bootstrap and the head reader import vendor modules, and they run at
    different times — so a path inserted only by the bootstrap left
    `_head_timestamp_us` importing nothing and returning None for every card.
    That failure is silent and lands as "the newest reviews sorted last", so the
    path setup belongs with the importers, not with one caller.
    """
    path = str(_scraper_dir())
    if path not in sys.path:
        sys.path.insert(0, path)


def _collect(driver, into: list[dict]) -> None:
    """Drain chromedriver's performance log into *into* (consume-on-read).

    Records EVERY batchexecute request, not just `RPC_ID`, and tags each with the
    rpcids its URL names. The log is consume-on-read, so a filter here is a
    filter forever: whatever this drops, nothing downstream can ask about. That
    cost was paid once already — the question "does some other rpcid serve the
    first page of reviews?" was unanswerable without a second 110s bootstrap.
    Callers filter with `_usable`.
    """
    for entry in driver.get_log("performance"):
        try:
            message = json.loads(entry["message"])["message"]
        except Exception:                    # noqa: BLE001 — malformed log line
            continue
        if message.get("method") != "Network.requestWillBeSent":
            continue
        request = (message.get("params") or {}).get("request") or {}
        url = request.get("url", "")
        if "batchexecute" not in url or not request.get("postData"):
            continue
        match = _RPCIDS_RE.search(url)
        into.append({"url": url,
                     "rpcids": match.group(1) if match else "",
                     "headers": dict(request.get("headers") or {}),
                     "body": request["postData"]})


def _usable(candidates: list[dict]) -> list[dict]:
    """Only the requests that are this module's review RPC."""
    return [c for c in candidates if maps_rpc.RPC_ID in (c.get("rpcids") or c["url"])]


def _observed_rpcids(*groups: list[dict]) -> dict[str, int]:
    """`{rpcids: count}` over every batchexecute seen — a diagnostic, not a gate."""
    seen: dict[str, int] = {}
    for group in groups:
        for candidate in group:
            key = candidate.get("rpcids") or "?"
            seen[key] = seen.get(key, 0) + 1
    return seen


def _best_capture(candidates: list[dict]) -> dict | None:
    """The candidate that starts EARLIEST in the review list.

    A request captured mid-scroll carries a cursor offset, and walking from it
    skips every review before it while still looking like a complete run —
    measured as 1,385 of a place's 1,395 reviews, which reads as Google
    returning slightly fewer rather than as a bug. Candidates whose body this
    module cannot rewrite are dropped here rather than at the first POST.
    """
    scored: list[tuple[int, dict]] = []
    for candidate in _usable(candidates):
        try:
            maps_rpc.build_body(candidate["body"], page_size=maps_rpc.MAX_PAGE_SIZE)
        except Exception:                    # noqa: BLE001 — unusable template
            continue
        offset = maps_rpc.cursor_offset(maps_rpc.cursor_of(candidate["body"]))
        scored.append((offset if offset is not None else 0, candidate))
    if not scored:
        return None
    offset, best = min(scored, key=lambda pair: pair[0])
    return best | {"start_offset": offset}


def _navigate_verified(driver, scraper, target: str, expected: str | None,
                       wait, log: Callable[[str], None]) -> dict:
    """Navigate to *target*, and go direct if the name search lands elsewhere.

    The vendored scraper reaches a place with `maps/search/<place name>/` — that
    is its documented bypass for Google's limited view, and it accepts whatever
    page comes back so long as it shows a reviews tab. For a name with siblings
    (a Cát Bà rental street has several near-identical shops) that is how a run
    ends up scraping a DIFFERENT business and reporting `completed`.

    So the search result is checked against the identity the caller's URL named,
    and on disagreement the vendor's own step-4 fallback — plain direct
    navigation — is used instead. Returns what happened; it does not raise,
    because the captured `f.req` is the authority and is verified separately.
    """
    attempts: list[dict] = []

    def _landed() -> str | None:
        return maps_rpc.feature_id_in(driver.current_url)

    scraper.navigate_to_place(driver, target, wait)
    scraper.dismiss_cookies(driver)
    attempts.append({"how": "vendor-search", "landed": _landed()})

    if expected and attempts[-1]["landed"] and not maps_rpc.same_feature(
            attempts[-1]["landed"], expected):
        log(f"name search landed on {attempts[-1]['landed']}, expected "
            f"{maps_rpc.normalize_feature_id(expected)} — navigating direct instead")
        direct = target if "hl=" in target else (
            target + ("&" if "?" in target else "?") + "hl=en")
        driver.get(direct)
        time.sleep(3)
        scraper.dismiss_cookies(driver)
        attempts.append({"how": "direct-url", "landed": _landed()})

    return {"attempts": attempts, "landed": attempts[-1]["landed"]}


def _bootstrap(target: str, *, headless: bool, proxy_url: str | None,
               expected_feature_id: str | None,
               log: Callable[[str], None],
               dump_page: Path | None = None) -> tuple[Any, dict]:
    """Load *target* in a browser and capture one usable qv9Egd request."""
    # NOT chdir(scraper_dir): SeleniumBase writes `downloaded_files/pyautogui.lock`
    # relative to the CWD, and the vendor checkout is root-owned while the service
    # runs as `placeintel` — measured on prod as PermissionError before the browser
    # ever started. The caller chooses a writable CWD; importing the vendor's
    # modules only needs it on sys.path.
    _ensure_vendor_importable()
    from seleniumbase import config as sb_config
    from seleniumbase.config import settings as sb_settings

    # Shared with the DOM path by default so chromedriver is downloaded once per
    # machine rather than once per run.
    driver_dir = Path(os.environ.get("PLACEINTEL_RPC_DRIVER_DIR",
                                     Path(tempfile.gettempdir()) / "maps-rpc-drivers"))
    driver_dir.mkdir(parents=True, exist_ok=True)
    # SeleniumBase's 9222 probe misreads half-dead listeners as free; multi_proxy
    # short-circuits to free_port(). Same workaround reviews.py uses.
    sb_config.multi_proxy = True
    sb_settings.NEW_DRIVER_DIR = str(driver_dir)
    sb_config.settings = sb_settings
    if proxy_url:
        sb_config.proxy = proxy_url
        sb_config.proxy_string = proxy_url

    from seleniumbase import Driver
    from selenium.webdriver.support.ui import WebDriverWait

    kwargs: dict[str, Any] = dict(uc=True, headless=headless, incognito=True,
                                  page_load_strategy="normal", log_cdp_events=True)
    if proxy_url:
        kwargs["proxy"] = proxy_url
    driver = Driver(**kwargs)
    try:
        driver.set_page_load_timeout(45)
        driver.set_window_size(1400, 3000)
        _force_english(driver)
        driver.get("https://www.google.com/robots.txt")
        # EU datacenter IPs get the consent interstitial and the vendor's
        # dismissal only matches English buttons, so seed the cookies instead.
        for name, value in (("SOCS", "CAI"), ("CONSENT", "PENDING+987"), ("PREF", "hl=en")):
            try:
                driver.add_cookie(dict(name=name, value=value, domain=".google.com"))
            except Exception as exc:         # noqa: BLE001 — best effort, reported
                log(f"cookie {name} failed: {exc}")
        driver.execute_cdp_cmd("Network.setExtraHTTPHeaders",
                               {"headers": {"Accept-Language": "en-US,en;q=0.9"}})

        import modules.scraper as vendor
        scraper = vendor.GoogleReviewsScraper(
            {"db_path": tempfile.mktemp(suffix=".db"), "scrape_mode": "full"})
        nav = _navigate_verified(driver, scraper, target, expected_feature_id,
                                 WebDriverWait(driver, 30), log)

        # Kept SEPARATE, not discarded. Requests fired before the sort describe
        # the relevance-ordered pane, and walking one of those returns "the
        # first N by relevance" while the caller asked for the newest N — a
        # curated subset with a real end, so it reports completeness it does not
        # have. They are only ever a last resort, and one that says so.
        presort: list[dict] = []
        candidates: list[dict] = []
        scraper.click_reviews_tab(driver)
        time.sleep(3)
        _collect(driver, presort)
        # set_sort also swaps the Overview teaser pane for the real reviews list
        # — without it the pane holds ~6 cards and never paginates, so no RPC
        # fires. Its own request restarts from the TOP of the newest ordering,
        # which is exactly the offset-0 template this capture wants.
        scraper.set_sort(driver, "newest")
        time.sleep(3)
        _collect(driver, candidates)

        # Sampled HERE, before any scrolling, and only once the pane has stopped
        # growing. Two things make the naive read wrong: Maps virtualises the
        # list, so cards scrolled out of view are REMOVED from the DOM (sampling
        # after the capture loop returned 3 ids); and the list repopulates
        # asynchronously after a re-sort, so an immediate read catches a partial
        # render (also 3).
        dom_review_ids = _settled_dom_ids(driver, log)
        # Read the cards NOW, before the capture loop scrolls. Maps virtualises
        # the pane — a card scrolled out of view is removed from the DOM — so
        # after scrolling there is no head left to read.
        head_reviews = _head_reviews(driver, dom_review_ids, log)
        listed = _listed_review_count(driver)

        scroller = driver.execute_script("""
            var c=document.querySelector('div[data-review-id]'); if(!c) return null;
            var e=c.parentElement;
            while(e&&e!==document.body){
              if(e.scrollHeight>e.clientHeight+40) return e; e=e.parentElement; }
            return null;""")
        for _ in range(MAX_CAPTURE_PASSES):
            best = _best_capture(candidates)
            if best is not None and best["start_offset"] == 0:
                break
            if scroller is not None:
                driver.execute_script(
                    "arguments[0].scrollTop=arguments[0].scrollHeight;", scroller)
            else:
                # No pane element found. Scrolling the window still provokes the
                # lazy load on some layouts, and costs nothing when it does not.
                driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
            time.sleep(1.5)
            _collect(driver, candidates)

        capture = _best_capture(candidates)
        sorted_capture = capture is not None
        if capture is None:
            capture = _best_capture(presort)
        if capture is None:
            # Say WHY. "no request observed" is three different failures wearing
            # one message: the pane never rendered, it rendered but never
            # paginated, or it paginated with a body this module cannot rewrite.
            raise maps_rpc.MapsRpcError(
                f"no usable {maps_rpc.RPC_ID} request observed — "
                f"{len(dom_review_ids)} review cards in the DOM, "
                f"scroller {'found' if scroller is not None else 'NOT found'}, "
                f"{len(candidates)} post-sort and {len(presort)} pre-sort candidates")
        if not sorted_capture:
            log("WARNING: no request captured after the sort — falling back to a "
                "pre-sort capture, which enumerates Google's RELEVANCE list "
                "(a curated subset that ends early, not the full history)")

        capture["headers"].setdefault(
            "User-Agent", driver.execute_script("return navigator.userAgent"))
        capture["cookies"] = {c["name"]: c["value"] for c in driver.get_cookies()}
        capture["landed_url"] = driver.current_url
        capture["navigation"] = nav
        capture["dom_review_ids"] = dom_review_ids
        capture["head_reviews"] = head_reviews
        capture["listed_review_count"] = listed
        capture["sorted_capture"] = sorted_capture
        capture["observed_rpcids"] = _observed_rpcids(presort, candidates)
        if dump_page is not None:
            _dump_page(driver, capture, dump_page, log)
        return driver, capture
    except BaseException:
        _quit(driver)
        raise


def _dump_page(driver, capture: dict, path: Path,
               log: Callable[[str], None]) -> None:
    """Write the bootstrapped page plus the non-secret parts of the capture.

    For answering "where did the missing reviews go?" offline, without paying
    another ~110s bootstrap per hypothesis. Deliberately writes NO cookies and
    NO headers: those carry the session and the BotGuard token, and a diagnostic
    artifact is the file most likely to be pasted somewhere public.

    It does carry real reviewers' names, text and photo URLs, because that is
    what the page is. Treat it as personal data — keep it out of the repo.
    """
    payload = {
        "landed_url": capture.get("landed_url"),
        "template": capture.get("body"),
        "cursor": maps_rpc.cursor_of(capture.get("body") or ""),
        "start_offset": capture.get("start_offset"),
        "dom_review_ids": capture.get("dom_review_ids"),
        "listed_review_count": capture.get("listed_review_count"),
        "sorted_capture": capture.get("sorted_capture"),
        "observed_rpcids": capture.get("observed_rpcids"),
        "page_source": driver.page_source,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log(f"dumped page diagnostics to {path} "
        f"({len(payload['page_source'] or ''):,} bytes of HTML)")


def _force_english(driver) -> None:
    """Append `hl=en` to every google.com navigation this driver performs.

    Not a nicety — a correctness fix, and the most expensive bug in this module.
    The prod box egresses from a German datacenter IP, so Maps renders in German,
    and the vendored scraper's `set_sort(driver, "newest")` matches English
    control labels only. It therefore no-ops SILENTLY, the pane stays on
    "Relevanteste", and the captured template walks the RELEVANCE list — which is
    a curated subset with a real end. Measured 2026-08-31: 74 reviews returned
    with `no next cursor — end of reviews` whose newest was `vor 6 Monaten`,
    while the page's own top card said `vor einer Woche`. Nothing errored.

    Setting `Accept-Language` and a `PREF` cookie is not enough: the vendor
    builds its own `maps/search/<name>/` URL internally, and that navigation
    carries neither. The DOM path already wraps `.get` for this reason; this is
    the same wrapper.
    """
    raw_get = driver.get

    def english_get(url):
        if isinstance(url, str) and "google.com" in url and "hl=" not in url:
            url = f"{url}{'&' if '?' in url else '?'}hl=en"
        return raw_get(url)

    driver.get = english_get


def _listed_review_count(driver) -> int | None:
    """How many reviews Google says the place has, or None if it did not say.

    This is the denominator the walk is missing. `no next cursor — end of
    reviews` is the server's word for "I have no more to give", which is not the
    same claim as "you have them all", and without a stated total the two are
    indistinguishable. None, never 0 — an unread count must not render as a
    place with no reviews.
    """
    try:
        text = driver.execute_script(
            "var m=document.body.innerText.match(/([\\d.,]+)\\s+reviews/i);"
            "return m?m[1]:null;")
    except Exception:                        # noqa: BLE001 — page shape varies
        return None
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else None


def _settled_dom_ids(driver, log: Callable[[str], None]) -> list[str]:
    """Unique review ids visible in the pane, in order, once it stops growing.

    DEDUPLICATED, and that is not tidiness. `div[data-review-id]` matches two
    elements per card on the live page, so a raw read of 20 elements is 10
    reviews — and this number is what the contiguity gate compares against the
    walk's start offset. Doubled, a 10-card head would "reach" offset 20 and
    report a clean merge across ten reviews nobody fetched.

    Order is preserved because it IS the newest-first order of the pane.
    """
    script = ("return Array.from(document.querySelectorAll('div[data-review-id]'))"
              ".map(e=>e.getAttribute('data-review-id'));")
    previous: list[str] = []
    for _ in range(PARITY_SETTLE_PASSES):
        current = [i for i in dict.fromkeys(driver.execute_script(script) or []) if i]
        # Stability, not a target count: the pane's size is Google's choice, so
        # "big enough" is not something this can wait for.
        if current and len(current) == len(previous):
            return current[:head_sample()]
        previous = current
        time.sleep(1.0)
    if len(previous) < PARITY_MIN_SAMPLE:
        log(f"reviews pane settled at only {len(previous)} cards — parity will "
            "report unverified rather than guess")
    return previous[:head_sample()]


_CONTRIB_RE = re.compile(r"/maps/contrib/(\d+)")


def _parse_relative_date_fallback(text: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if re.fullmatch(r"\s*(just now|now|a moment ago|moments ago)\s*", text, re.IGNORECASE):
        return now
    pattern = re.compile(
        r"(?P<num>a|an|\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    num_str = m.group("num").lower()
    num = 1 if num_str in ("a", "an") else int(num_str)
    unit = m.group("unit").lower()
    if unit == "second":
        delta = timedelta(seconds=num)
    elif unit == "minute":
        delta = timedelta(minutes=num)
    elif unit == "hour":
        delta = timedelta(hours=num)
    elif unit == "day":
        delta = timedelta(days=num)
    elif unit == "week":
        delta = timedelta(weeks=num)
    elif unit == "month":
        delta = timedelta(days=30 * num)
    elif unit == "year":
        delta = timedelta(days=365 * num)
    else:
        return None
    return now - delta


def _head_timestamp_us(relative: Any) -> int | None:
    """Absolute microseconds for a relative date string like "2 weeks ago".

    APPROXIMATE by construction — the DOM states no absolute date — and that is
    accepted here because the DOM path already stores every one of its reviews
    this way. What is not acceptable is leaving it None: `_order_and_cap` sorts
    on `review_date or ""` descending, so an undated row sinks to the bottom and
    is the FIRST thing a `max_reviews` cap discards. These are the newest
    reviews on the page, so that would throw away exactly what this merge exists
    to recover.

    None when the string cannot be parsed. Never "now" — that is a fabricated
    date, and it would sort an unknown-age review to the very top.
    """
    if not isinstance(relative, str) or not relative.strip():
        return None
    moment = None
    try:
        _ensure_vendor_importable()
        from modules.date_converter import relative_to_datetime
        moment = relative_to_datetime(relative, "en")
    except Exception:                        # noqa: BLE001 — vendor absent/changed
        moment = None
    if moment is None:
        moment = _parse_relative_date_fallback(relative)
    if moment is None:
        return None
    try:
        # The vendor builds these from `datetime.utcnow()`, so they are NAIVE
        # UTC. `.timestamp()` on a naive datetime assumes LOCAL time, and prod
        # runs CEST — a two-hour shift, which is enough to file a review under
        # the wrong day near midnight and to date a "2 hours ago" review in the
        # future.
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return int(moment.timestamp() * 1_000_000)
    except (OverflowError, OSError, ValueError):
        return None


def _head_review(raw: Any) -> maps_rpc.Review:
    """One vendor `RawReview` as the same `Review` the RPC walk yields.

    One shape, so `reviews.py` keeps a single mapper and both halves dedupe on
    the same primary key. Every falsy field becomes None: the vendor's defaults
    are 0.0 and "", which mean "no selector matched", and forwarding them would
    publish a confident 0-star review by an author named "".
    """
    rating = getattr(raw, "rating", None)
    profile = getattr(raw, "profile", "") or ""
    contributor = _CONTRIB_RE.search(profile) if isinstance(profile, str) else None
    relative = getattr(raw, "date", "") or None
    return maps_rpc.Review(
        review_id=getattr(raw, "id", "") or None,
        rating=int(rating) if isinstance(rating, (int, float)) and rating else None,
        text=getattr(raw, "text", "") or None,
        author=getattr(raw, "author", "") or None,
        author_id=contributor.group(1) if contributor else None,
        author_avatar=getattr(raw, "avatar", "") or None,
        relative_date=relative,
        timestamp_us=_head_timestamp_us(relative),
        photos=tuple(getattr(raw, "photos", ()) or ()),
    )


def _head_reviews(driver, ids: list[str],
                  log: Callable[[str], None]) -> list[maps_rpc.Review]:
    """Read the on-screen review cards through the VENDOR's own DOM extractor.

    Not a second parser. `modules/dom_batch.py` owns every review selector in
    this codebase and the DOM scraper path already reads all 85 of this place's
    reviews through it; reimplementing the card here would be a private fork of
    the one file that has to change when Google renames a class.

    Never raises. The head is an improvement on the walk, so failing to read it
    must degrade to "no head" — which the contiguity gate then reports as a gap —
    rather than take down a run the walk alone would have survived.
    """
    if not ids:
        return []
    try:
        _ensure_vendor_importable()
        from modules import dom_batch
        from modules.models import RawReview
    except Exception as exc:                 # noqa: BLE001 — vendor absent
        log(f"head skipped: vendor DOM extractor unavailable ({exc})")
        return []
    try:
        expanded = dom_batch.expand_more(driver, ids)
        if expanded and expanded.get("clicked"):
            # Expansion mutates the DOM; let it settle before reading back, or
            # the long reviews are stored truncated at "… More".
            time.sleep(head_expand_settle_s())
        payloads = dom_batch.extract_cards(driver, ids)
    except Exception as exc:                 # noqa: BLE001 — best effort
        log(f"head skipped: {type(exc).__name__}: {exc}")
        return []
    if not payloads:
        log(f"head skipped: the DOM extractor returned nothing for {len(ids)} cards")
        return []

    out: list[maps_rpc.Review] = []
    seen: set[str] = set()
    empty = 0
    for payload in payloads:
        if not isinstance(payload, dict) or not payload.get("id"):
            continue
        if payload["id"] in seen:
            # Two elements per card, so the extractor yields each review twice.
            continue
        seen.add(payload["id"])
        if dom_batch.is_empty_payload(payload):
            # Every content selector came back empty — an id with no review
            # behind it. Storing it would create a blank review.
            empty += 1
            continue
        try:
            out.append(_head_review(RawReview.from_payload(payload)))
        except Exception:                    # noqa: BLE001 — one bad card
            empty += 1
    undated = sum(1 for r in out if r.timestamp_us is None)
    log(f"head: {len(out)} of {len(ids)} on-screen cards read"
        + (f", {empty} unreadable" if empty else "")
        + (f", {undated} without a usable date" if undated else ""))
    return out


def parity_verdict(dom_review_ids: Iterable[str] | None,
                   rpc_review_ids: Iterable[str] | None) -> dict:
    """Do the DOM and the RPC agree they are describing the same business?

    Compared against the WHOLE walk, not its first page. Head-to-head only lines
    up when both start at the same offset, and a cursor-offset artefact then
    reads as total disjointness — measured as `3 vs 20, overlap 0` on a run that
    was in fact correct.

    Deliberately the WEAKER of the two gates. Sort order and timing legitimately
    shift which reviews are on screen, so only a complete disjointness with data
    present on BOTH sides is evidence of a problem; either side empty is
    `unverified`, which is not a failure but is also not a pass.
    """
    dom = {i for i in (dom_review_ids or ()) if i}
    rpc = {i for i in (rpc_review_ids or ()) if i}
    overlap = len(dom & rpc)
    if overlap:
        verdict = "match"
    elif not rpc or len(dom) < PARITY_MIN_SAMPLE:
        # Too little to conclude from. Measured: a 3-card sample, caught while
        # the re-sorted pane was still filling in, disagreed completely with a
        # walk that was correct — identity matched, all 75 reviews present.
        # Calling that a mismatch would reject good data on a rendering artefact.
        verdict = "unverified"
    else:
        verdict = "no-overlap"
    return {"dom_ids": len(dom), "rpc_ids": len(rpc),
            "overlap": overlap, "verdict": verdict}


def _quit(driver) -> None:
    """Close the browser, at most once, never raising.

    The walk closes it deliberately (everything after the bootstrap is plain
    HTTP) while `fetch` keeps a `finally` for the paths that do not get that
    far. A second `quit()` on a dead driver raises a connection error, and
    raising from a `finally` would replace a good result with that error.
    """
    try:
        driver.quit()
    except Exception:                        # noqa: BLE001 — already gone
        pass


def _identity(capture: dict, expected: str | None) -> tuple[str, str | None]:
    """(verdict, landed_feature_id). 'unverified' when either side is unknown."""
    landed = maps_rpc.feature_id_of(capture["body"])
    if landed is None or maps_rpc.normalize_feature_id(expected) is None:
        return "unverified", landed
    return ("match" if maps_rpc.same_feature(landed, expected) else "mismatch"), landed


def fetch(target: str, *, max_reviews: int | None = None,
          expected_feature_id: str | None = None, proxy_url: str | None = None,
          headless: bool = True, page_size: int = maps_rpc.MAX_PAGE_SIZE,
          log: Callable[[str], None] = _noop,
          dump_page: Path | None = None) -> dict:
    """Bootstrap, verify identity, then walk the reviews over plain HTTP."""
    started = time.time()
    driver, capture = _bootstrap(target, headless=headless, proxy_url=proxy_url,
                                 expected_feature_id=expected_feature_id, log=log,
                                 dump_page=dump_page)
    # The browser handle is owned from HERE, so everything that can raise between
    # now and quit() lives inside the try. A `finally` placed after a few more
    # "safe" statements is a Chrome process tree waiting for one of them to be
    # less safe than it looked.
    try:
        return _verify_and_walk(driver, capture, started, log=log, proxy_url=proxy_url,
                                expected_feature_id=expected_feature_id,
                                page_size=page_size, max_reviews=max_reviews)
    finally:
        _quit(driver)


def _rewind(post, template: str, page_size: int,
            log: Callable[[str], None]) -> str:
    """Move a captured template back to the start of the review list.

    The bootstrap can only capture a request the page chose to make, and that
    cursor carries an offset — so a walk from it silently omits the newest N
    reviews while still reporting a clean "end of reviews". Measured: offset 10
    on a place with ~85 reviews, i.e. the 10 most recent were unreachable.

    The rewind is ATTEMPTED, not assumed: the cursor is an opaque blob and the
    server is free to reject a hand-edited one, which it would do the same way
    it rejects everything else — HTTP 200 with an empty envelope. So the rewound
    body is sent once and kept only if it actually answers.
    """
    cursor = maps_rpc.cursor_of(template)
    offset = maps_rpc.cursor_offset(cursor)
    if not offset:
        return template
    rewound = maps_rpc.build_body(
        template, page_size=page_size, cursor=f"{cursor.rsplit(':', 1)[0]}:0")
    page = maps_rpc.parse_page(post(rewound))
    if not (page.has_payload and page.reviews):
        log(f"WARNING: cursor rewind rejected — walking from offset {offset}, so "
            f"the {offset} newest reviews are not reachable")
        return template

    # "It answered" is NOT evidence that it rewound. Measured: the server accepts
    # `<blob>:0` and returns the SAME rows, because the numeric suffix is
    # decorative — the position lives inside the opaque blob. The old check
    # passed on that and recorded start_offset 0 for a walk that still began at
    # 10, which would let the contiguity gate below compare against a zero it
    # invented and call a ten-review hole contiguous.
    original = maps_rpc.parse_page(post(maps_rpc.build_body(template, page_size=page_size)))
    if (original.reviews
            and original.reviews[0].review_id == page.reviews[0].review_id):
        log(f"WARNING: cursor rewind accepted but returned the same first review "
            f"— still walking from offset {offset}; the head merge covers it")
        return template
    log(f"rewound the captured cursor from offset {offset} to 0")
    return rewound


def _verify_and_walk(driver, capture: dict, started: float, *,
                     log: Callable[[str], None], proxy_url: str | None,
                     expected_feature_id: str | None, page_size: int,
                     max_reviews: int | None) -> dict:
    import requests

    bootstrap_secs = round(time.time() - started, 1)
    result: dict[str, Any] = {
        "ok": False,
        "reviews": [],
        "bootstrap_secs": bootstrap_secs,
        "walk_secs": 0.0,
        "pages": 0,
        "start_offset": capture.get("start_offset"),
        "landed_url": capture.get("landed_url"),
        "navigation": capture.get("navigation"),
        "expected_feature_id": maps_rpc.normalize_feature_id(expected_feature_id),
        "missing_required_headers": list(maps_rpc.missing_headers(capture["headers"])),
        "sorted_capture": capture.get("sorted_capture"),
        "error": None,
    }
    verdict, landed = _identity(capture, expected_feature_id)
    result["identity"] = verdict
    result["landed_feature_id"] = landed

    if verdict == "mismatch":
        # Refuse rather than store. This is the failure that is otherwise
        # silent: the RPC answers correctly about the WRONG listing.
        result["error"] = (f"landed on {landed}, expected "
                           f"{result['expected_feature_id']}")
        log(f"IDENTITY MISMATCH — {result['error']}")
        return result
    if result["missing_required_headers"]:
        log(f"WARNING: capture is missing {result['missing_required_headers']}")
    if result["start_offset"]:
        # Informational, not a warning. A non-zero offset is the normal shape:
        # Maps renders the first ~10 cards server-side, so the page's own first
        # request already begins after them. The head merge covers exactly that
        # span, and the contiguity gate below proves it did.
        log(f"walk begins at cursor offset {result['start_offset']}; the "
            f"{len(capture.get('head_reviews') or ())} on-screen cards cover the head")
    # Closed before the first RPC call: everything below is plain HTTP.
    _quit(driver)

    session = requests.Session()
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})

    def post(body: str) -> bytes:
        response = session.post(capture["url"], headers=capture["headers"],
                                cookies=capture["cookies"], data=body, timeout=45)
        return response.content

    template = _rewind(post, capture["body"], page_size, log)
    result["start_offset"] = maps_rpc.cursor_offset(maps_rpc.cursor_of(template))
    stats = maps_rpc.WalkStats()
    walk_started = time.time()
    reviews = list(maps_rpc.walk(post, template, page_size=page_size,
                                 max_reviews=max_reviews, stats=stats))
    result["walk_secs"] = round(time.time() - walk_started, 1)
    result["pages"] = stats.pages
    result["stopped_because"] = stats.stopped_because
    result["walked"] = len(reviews)

    # The head — the cards Maps rendered server-side, which the RPC cannot reach
    # because the page's own first request already starts after them.
    head = list(capture.get("head_reviews") or ())
    merged, merge = maps_rpc.merge_head(head, reviews, start_offset=result["start_offset"])
    result["merge"] = merge.__dict__.copy()
    result["reviews"] = [r.__dict__ | {"photos": list(r.photos)} for r in merged]

    # Retained as a DIAGNOSTIC, no longer a gate: the head and the walk are
    # disjoint by construction now that the head is merged deliberately, so
    # "no-overlap" is the healthy shape. Contiguity and coverage below replace
    # it, and both are exact rather than heuristic.
    result["parity"] = parity_verdict(capture.get("dom_review_ids"),
                                      [r.review_id for r in reviews])
    result["parity"]["dom_sample"] = list(capture.get("dom_review_ids") or ())[:5]

    listed = capture.get("listed_review_count")
    result["listed_review_count"] = listed
    result["coverage"] = round(len(merged) / listed, 3) if listed else None
    floor = min_coverage()
    result["min_coverage"] = floor

    if not reviews:
        # The failure shape of this endpoint is HTTP 200 with an empty envelope,
        # so an empty walk is a failure and must not read as "no reviews".
        result["error"] = f"walk returned no reviews ({stats.stopped_because})"
    elif merge.verdict == "gap":
        # Reviews exist that are in neither half. Every other signal still looks
        # healthy here — the walk ended cleanly and the ids are all distinct — so
        # without this the result reads as complete.
        result["error"] = (
            f"gap of {merge.gap} review(s): the {merge.head} cards on screen do not "
            f"reach the walk's start at offset {merge.start_offset}, so those "
            f"{merge.gap} are in neither half")
    elif listed and result["coverage"] < floor:
        # Refuse rather than store a short read. Falling back to the DOM scraper
        # costs ~70s and returns everything; storing 87% spends the speed on an
        # answer no reader can distinguish from a complete one.
        result["error"] = (
            f"got {len(merged)} of the {listed} reviews Google lists "
            f"({result['coverage']:.0%}, floor {floor:.0%})")
    else:
        result["ok"] = True

    if listed is None:
        log("Google did not state a review count — coverage is unverified, not 100%")
    elif len(merged) < listed:
        log(f"{len(merged)} of the {listed} reviews Google lists "
            f"({result['coverage']:.0%}); head {merge.head} + walked {merge.walked} "
            f"- {merge.overlap} shared")
    return result


# ---------------------------------------------------------------------------
# CLI — how reviews.py invokes this, under the vendored scraper's venv
# ---------------------------------------------------------------------------

def _stderr(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        # Pinned, unusually, rather than derived from argv[0]: this module uses a
        # relative import, so the path argparse would print
        # (`placeintel/maps_rpc_fetch.py`) is not a runnable command. The -m form
        # is the only one that works, so it is the only one worth printing.
        prog="python -m placeintel.maps_rpc_fetch",
        description="Fetch a place's reviews over the qv9Egd batchexecute RPC.")
    ap.add_argument("url", help="Google Maps place URL")
    ap.add_argument("--max", type=int, default=None, help="stop after N reviews")
    ap.add_argument("--page-size", type=int, default=maps_rpc.MAX_PAGE_SIZE)
    ap.add_argument("--expect-feature", default=None,
                    help="feature id (0x…:0x…) the URL named; refuses on mismatch")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--out", type=Path, required=True, help="write the result JSON here")
    ap.add_argument("--dump-page", type=Path, default=None,
                    help="also write the bootstrapped page HTML and the non-secret "
                         "capture fields here, for offline diagnosis. Contains real "
                         "reviewers' personal data — never commit it.")
    args = ap.parse_args(argv)

    result = fetch(args.url, max_reviews=args.max, page_size=args.page_size,
                   expected_feature_id=args.expect_feature, proxy_url=args.proxy,
                   headless=not args.no_headless, log=_stderr,
                   dump_page=args.dump_page)
    args.out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "reviews"}
    summary["reviews"] = len(result["reviews"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def _shutdown(*_):
    raise KeyboardInterrupt("signal")


if __name__ == "__main__":
    # A `finally` does not run on SIGTERM — CPython's default handler _exit()s
    # without unwinding — and this owns a Chrome process tree.
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    code = 1
    try:
        code = main()
    except SystemExit as exc:
        # argparse exits this way for --help and for a usage error; reporting
        # those as a crash puts a traceback in front of the first-time reader.
        code = exc.code if isinstance(exc.code, int) else 0
    except BaseException as exc:             # noqa: BLE001 — top-level reporter
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        traceback.print_exc()
    sys.exit(code)
