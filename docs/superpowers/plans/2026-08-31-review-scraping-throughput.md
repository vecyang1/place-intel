# Review scraping throughput & completeness — working owner

Status: INVESTIGATING (started 2026-08-31)
Target: cloud deployed version (prod = contabo-n8n `/opt/gmr/app`, systemd `placeintel.service`)

## The two complaints

1. Review scraping is slow. Can we parallelize?
2. Place lists **1,395** reviews on Google; we intake ~158 (user-reported) / **97** (measured in prod db).

## Measured facts (evidence, not guesses)

| Fact | Evidence | Measured |
|---|---|---|
| Prod version | `cat /opt/gmr/app/placeintel/__init__.py` | `0.4.78` |
| Prod deploy dir is NOT a git repo | `git -C /opt/gmr/app log` → `fatal: not a git repository` | rsync/tarball deploy |
| Prod has the local uncommitted `reviews.py` diff | `grep -n scrape_mode /opt/gmr/app/placeintel/reviews.py` → line 230 `"refresh" if target_limit > 50` | yes |
| Place identity | prod `placeintel.db` | `ChIJGSOhZTRESjERzhfaGlo7ql0`, review_count **1395**, rating 5.0 |
| Google feature id | resolved live via `/maps/place/?q=place_id:…` | `0x314a443465a12319:0x5daa3b5a1ada17ce` |
| Scraper-pro internal key | prod `scraper_pro_reviews.db.places` | `0x314a443465a12319:0` (second half truncated to `0`) |
| Rows in **scraper** db for the place | `SELECT COUNT(*) … WHERE place_id='0x314a443465a12319:0'` | **281** (0 deleted) |
| Rows in **app** db for the place | `SELECT source,COUNT(*) … placeintel.db` | **97** (source=scraper-pro) |
| Session 128 | `scrape_sessions` | completed, `reviews_found=300`, `reviews_new=300`, 05:23:38 → 05:38:56 = **15m18s** |
| Orphaned sessions | `scrape_sessions` rows 125,126,129 | status `running`, never completed |
| `max_reviews` default | `server.py:68,80`; `cli.py:910`; `cache.py:148` | **300** hard default |

### Gap decomposition (1395 → 97)
- 1395 → 300: **`max_reviews` default cap of 300** (config, not a bug).
- 300 → 281: scraper dedup / partial.
- 281 → 97: **UNEXPLAINED LOSS — the real bug.** Rows exist in the scraper db but never landed in `placeintel.db`.

## Speed baseline (measured)
- Selenium scroll path: **15m18s for 300 reviews** ≈ 3.06 s/review, single Chrome, single place.
- Cross-place concurrency already exists: `pipeline.py:198` ThreadPoolExecutor(max_workers=min(len,4)).
- Intra-place concurrency: **none** — one Chrome scrolls one pane sequentially. This is the bottleneck for a 1395-review place.

## Hypotheses under test
- H1 (fast path): Google's `/maps/rpc/listugcposts` returns 20 reviews/request as JSON. First naive probe → **HTTP 403** even with warmed SOCS/CONSENT/NID cookies. Need the *current* `pb` format captured from a live browser before declaring it dead.
- H2 (loss): concurrent scraper subprocesses share one SQLite `scraper_pro_reviews.db` → lock contention / partial reads. Orphaned `running` sessions support this.
- H3 (loss): `_read_scraper_db` runs before the subprocess finishes writing, or the early-return in `_fetch_via_scraper_pro` returns a stale partial set.
- H4 (loss): `cache.upsert_reviews` dedupes/drops rows (review_id collision).

## Not yet verified
- Whether the 403 on listugcposts is format or policy.
- Which of H2/H3/H4 causes the 281→97 loss.

---

# ROOT CAUSES — measured, 2026-08-31

## Correction to the opening numbers
Prod moved while we measured. `281` and `97` were mid-flight reads of a still-running
session 129. Stable numbers for the *completed* session 128: **300 scraped → 91 committed**.
Vendor db now 311, app db now 314. The gap is real but it is a *transient* that resolves
minutes later — which is exactly why the user saw "158".

## RC-1 — `FOREIGN KEY constraint failed`: 300 scraped, 91 stored  ← the intake gap
Two scrapes of the SAME place ran concurrently (sessions 128 and 129 overlap by 2m20s).
Evidence, `/opt/gmr/app/data/vendor/.../logs/scraper.log`:
```
07:35:53 WARNING Error during review processing: FOREIGN KEY constraint failed
07:36:36 Registered place: 0x314a443465a12319:0     <- run B re-registers while run A inserts
07:38:56 Finished - new: 300, updated: 0 ...
07:38:56 Total unique reviews in DB: 91
```
`batch_stats[result] += 1` (vendor `scraper.py:1707`) counts *attempted* upserts; the outer
`except Exception: log.warning(...)` at `scraper.py:1852` swallows the FK failure. So the
"300" in `reviews_found` is a lie and 209 rows were dropped on the floor.
Trigger: `_clear_scraper_db_entry` (placeintel/reviews.py:451) hard-DELETEs the `places` row
that run A's in-flight review inserts still reference.

## RC-2 — nothing serialises scrapes of the same place
No lock, semaphore, or per-place mutex anywhere. `server.py:215` spawns an unbounded
`threading.Thread` per HTTP request. Hitting refresh twice = two Chrome trees on one place.

## RC-3 — orphaned Chrome, 4.7 GB live on prod right now
`subprocess.run(..., timeout=SCRAPER_TIMEOUT_S)` (reviews.py:344) SIGKILLs only the direct
child. No `start_new_session=True` anywhere in placeintel/ or vendor/. Measured on prod:
54 chrome processes, 4 orphaned trees, `PPid 1`, **4718 MB RSS**, swap 74% used.
systemd unit has `MemoryMax=infinity`, no CPU quota.

## RC-4 — the 15m18s is O(n²) WebDriver chatter, not Google throttling
Measured, session 129 (the clean single-process window):
| component | file:line | seconds (300 reviews) |
|---|---|---|
| parse+upsert, 25–30 round trips **per review** | vendor `models.py:80-176` | **345** |
| full-DOM dedup rescan every iteration, `0.077s × n` | vendor `scraper.py:1649-1651` | **358** |
| fixed sleeps + scroll actions | `scraper.py:1836-1841` | **150** |
Fit from 1018 log samples: `T_idle(n) = 2.1 + 0.077·n`. Zero use of `execute_script` for
extraction. ~12,600 WebDriver round trips where a batched extractor needs ~60.
`get_attribute` in Selenium 4.44 ships a 4754-byte JS atom **per call** (~58 MB/run).

## RC-5 — `max_reviews=300` is what stopped it, not Google
Log: `Reached max_reviews limit (300), stopping.` Google served 610 / 530 / 506 / 480 rows
for other places by scrolling, so the pane goes well past 300. Whether it serves >300 for
THIS place is **UNKNOWN — never tested**, because the cap always fired first.
`max_scroll_attempts` is dead code (`attempts` resets on every accepted review, `scraper.py:1715`).
The stop message is a shared string and prints "No new reviews found after 25 scroll attempts"
even when the cause was the cap — a wrong diagnosis printed on a correct stop.

## RC-6 — the residential proxy fallback is DEAD CODE in production
`proxy.resolve_residential_proxy()` needs one of `PLACEINTEL_RESIDENTIAL_PROXY_URL` /
`DATAIMPULSE_PROXY_URL` / `SCRAPER_PROXY_URL`, or `~/.cache/ultra-low-cost-scraper/proxy_cache.json`,
or `$HOME/.agents/skills/ultra-low-cost-scraper/scripts/proxy_resolver.py`.
Measured on prod: **none of the three exists** (checked for both `root` and `placeintel`).
So commit 98b14ac ships a fallback that can never fire on the deployed box.
Locally the credentials DO work — measured DataImpulse VN residential egress
222.253.218.80 / 14.250.142.39 / 113.186.108.49 at 1.2–1.6 s/request.

## RC-7 — limited view is real, and search-navigation is the only thing beating it
Measured on prod with headless Chrome on the direct place URL
(`/maps/place/?q=place_id:…`): tabs are **`['Overview', 'About']` — no Reviews tab**,
0 review cards. Via the vendor's search-based navigation
(`/maps/search/<name>/@lat,lng,17z`): tabs are **`['Overview', 'Reviews', 'About']`**,
20 cards on tab-click, 180 after scrolling. So the search path is load-bearing, not optional.

## Direct-JSON path: NOT yet available
`/maps/rpc/listugcposts` returns HTTP 403 for every `pb` variant tried (classic, 1m7+3s*,
minimal, no-flags) — **identically from a datacenter IP and from residential VN IPs**, so
the 403 is FORMAT, not policy. Ground-truth capture from a live browser is in progress.

---

# EXPERIMENTS — 2026-08-31

## E1 — Is the limited view caused by the IP, or by the URL form?
2×2, headless Chrome, same cookies, same place.

| egress | URL form | tabs rendered | review cards |
|---|---|---|---|
| direct 14.191.43.214 | `/maps/place/?q=place_id:…` | `Overview, About` | 0 |
| **residential 42.115.113.160 (VN)** | `/maps/place/?q=place_id:…` | **`Overview, About`** | **0** |
| direct (prod datacenter) | `/maps/search/<name>/@lat,lng,17z` | **`Overview, Reviews, About`** | 20 → 180 after scroll |

**Conclusion: the limited view is a property of the URL form, not the egress IP.**
A residential IP does NOT unlock the Reviews tab on a `?q=place_id:` deep link.
Search-based navigation is therefore load-bearing and cannot be swapped for
residential IPs. Residential IPs remain useful for a *different* failure mode
(rate-limiting under volume), not for this one.

## E2 — Does `/maps/rpc/listugcposts` work as a direct JSON path?
HTTP **403** for every `pb` variant tried (classic `1m6`, `1m7`+`3s*`, minimal,
no-flags, `listentitiesreviews`), **identically from a datacenter IP, from prod,
and from residential VN IPs**. So the 403 is a request-format rejection, not a
policy block. A live-browser capture of the current format is still outstanding —
the page issues no `/maps/rpc/` request that either a fetch/XHR hook or resource
timing observes, so the reviews arrive by some transport neither instrument sees.
**Status: UNKNOWN, not disproven. Not on the critical path — see E4.**

## E3 — Does production's residential-proxy path actually work? **NO.**
`Driver(uc=True, headless=True, proxy="user:pass@host:port")` — exactly what
`reviews._run_scraper_pro` passes today — loaded an **empty page** (egress `""`,
no title, no tabs). SeleniumBase implements proxy auth with a generated Chrome
extension, and extensions do not load in this headless mode.
So RC-6 is worse than "credentials not deployed": **even with credentials
deployed, the fallback would silently fail.** A local credential-injecting relay
(Chrome talks to 127.0.0.1 with no auth) is measured working: egress
222.254.200.8 / 42.115.113.160 via `requests`, 1.2–1.6 s/request.

## E4 — Where the 15 minutes actually goes
703 of the 955 s are our own O(n²) DOM chatter, entirely under our control and
independent of Google's private API staying stable. That is the critical path,
not the RPC endpoint.

---

# SHIPPED — commit 3ed06a1, deployed to prod 2026-08-31 08:44 CEST

## What landed
| Change | File | Fixes |
|---|---|---|
| Cross-process place lock + browser-slot ceiling | `placeintel/scrape_lock.py` (new) | RC-1, RC-2 |
| Refresh wipe + scrape + read-back inside one lock | `placeintel/reviews.py` | RC-1 |
| Non-refresh early-return read moved inside the lock | `placeintel/reviews.py` | mid-scrape partial reads |
| Process-group launch + `killpg` on timeout | `placeintel/reviews.py` | RC-3 |
| `_clear_scraper_db_entry` raises instead of `except: pass`, 30 s busy_timeout | `placeintel/reviews.py` | silent no-op refresh |
| Loopback credential-injecting proxy | `placeintel/proxy_relay.py` (new) | RC-6 / E3 |
| `MemoryHigh=5G MemoryMax=6G TasksMax=4096` | `deploy/remote-bootstrap.sh` + live drop-in | RC-3 backstop |
| Proxy + concurrency env plumbed through deploy | `.github/workflows/deploy-contabo.yml`, `.env.example` | RC-6 |

## Verification
- `237 tests OK` (was 230 + 7 new; the one red test was my own misplaced plan file
  tripping the `tasks/` PRD-name contract, now filed under `docs/superpowers/plans/`).
- Both new suites mutation-checked: RED under a no-op flock and under a dropped
  `Proxy-Authorization`; GREEN restored.
- Prod cleanup: 48 orphaned Chrome processes / **4.7 GB** reclaimed; `used` fell
  6701 → 5451 MB, service kept the same MainPID, health 200 throughout.
- Prod E2E, two concurrent `refresh=True` scrapes of the same place:
  `data/locks/` holds **one** place lock and **one** slot lock, `scrape_sessions`
  shows **one** running session (130) where the incident had two overlapping
  (128+129), 11 Chrome processes = exactly one browser tree, and
  **0 new `FOREIGN KEY constraint failed`** in the vendor log.

## BLOCKER — the GitHub Actions deploy is disabled by billing, not by code
```
The job was not started because recent account payments have failed or your
spending limit needs to be increased.
```
Runs 33365033845 / 33357767263 / 33357542283 all failed in 3–4 s at job start.
That is why `/opt/gmr/app` carries mixed ownership and root-owned hand-copied
files, and why prod ran uncommitted code. **This deploy was applied by rsync,
mirroring the CI step exactly.** Until billing is restored:
- CI's test gate does NOT run before a deploy;
- `/opt/gmr/app/.env` is NOT regenerated, so manual entries persist (they would
  be overwritten the moment CI works again — the workflow now writes both new
  keys, so that transition is safe).

## Still open
- `PLACEINTEL_RESIDENTIAL_PROXY_URL` is not set on prod. The relay makes it
  *work*; the value still has to be provided by its owner.
- `max_reviews` default stays 300. The UI already exposes the field
  (`web/index.html:71,118`, min 20, no max; server caps at 5000), so 1395 is
  reachable today by typing it. Raising the DEFAULT is only sensible after the
  scroll-loop speedup, or every scrape gets ~4x slower.
- Concurrent `gosom` discovery containers collide: two simultaneous
  `placeintel shop` runs both returned `0 entries`, one with `gosom exited 137`
  (SIGKILL). Separate from the review path; not yet diagnosed.

---

# PROD E2E RESULT — 2026-08-31 09:00 CEST

Two concurrent `refresh=True` scrapes of the Cát Bà place, driven through
`reviews.fetch_reviews` on the deployed box.

```
RESULT: {'tag': 'A', 'n': 300, 'secs':  954.9, 'error': None}
RESULT: {'tag': 'B', 'n': 300, 'secs': 1900.8, 'error': None}
TOTAL_WALL=1903.8s   SCRAPER_DB_ROWS=300
RECENT_SESSIONS=[(131,'completed',300), (130,'completed',300),
                 (129,'completed',300), (128,'completed',300)]
chrome processes after: 0
```

B's 1900.8 s is A's 954.9 s of waiting plus its own ~946 s scrape — that number
*is* the serialisation proof, and it is also why refresh coalescing was added
afterwards: B re-fetched data A had just fetched. All four sessions closed
`completed`; none was left at `running`, which is what the process-group kill
buys. Zero Chrome processes survived.

| | before (session 128) | after (session 130) |
|---|---|---|
| reviews scraped | 300 | 300 |
| **reviews returned to the app** | **91** | **300** |
| concurrent sessions on the place | 2 (128 + 129, overlapping 2m20s) | 1 |
| new `FOREIGN KEY constraint failed` | yes | **0** |
| Chrome processes | 2 trees (~22 procs) | 1 tree (11 procs) |
| orphaned trees left behind | 4 (4.7 GB) | 0 |

`data/locks/` held exactly one `place-*.lock` and one `slot-0.lock` for the
duration. Deploy-smoke on prod: health / static_version / library (235 places) /
dossier all `ok`, version 0.4.78.

**954.9 s for 300 reviews is the pre-speed-fix baseline** — 3.18 s/review, within
0.6 s of the 955.47 s the forensic log analysis predicted. That is the number the
batching work has to beat.

## Follow-on defects found and fixed while verifying (commit 6fc2d40)
- `?q=place_id:X` URLs carried no identity → Maps text-searched the literal
  string → `gosom returned 0 entries` for a cached place. Two functions in this
  package *generate* that URL shape, so the round-trip is now asserted against
  the generators, not a hand-written fixture.
- Back-to-back refreshes scraped twice. A scrape that completes *after* a caller
  asked now satisfies that caller. Boundary asserted both ways so `refresh`
  cannot decay into "recent enough".

---

# Independent benchmark of the batching premise (offline, no Google)

300 review-shaped cards in a local `data:` HTML fixture, headless Chrome, same
driver stack the scraper uses. This checks the premise behind the speed rewrite
without depending on the rewrite's own reasoning.

| method | 300 cards | per card | vs per-element |
|---|---|---|---|
| `for c in cards: c.get_attribute(...)` — today's code | **1.547 s** | 5.2 ms | 1× |
| one `execute_script`, ids only | **0.006 s** | 0.02 ms | **250×** |
| one `execute_script`, all five fields | **0.010 s** | 0.03 ms | **161×** |

Ids from both paths were asserted equal, so this is the same work, not less work.

Note the local 5.2 ms/card against the 77 ms/card regressed from prod's logs:
the prod box is slower, loaded, and holds a real Google DOM rather than 300 flat
divs. The ratio is what transfers, and it is enormous either way. Together the
per-review parse (345 s) and the full-DOM rescan (358 s) are 703 s of the
measured 955 s, and both are pure round-trip cost.

---

# BATCHING RESULT — measured on prod, same place, same box

```json
{"returned": 300, "secs": 153.7, "s_per_review": 0.512,
 "baseline_secs": 954.9, "baseline_s_per_review": 3.183, "speedup_x": 6.21,
 "scraper_rows_after": 300, "overlap_with_previous_ids": 300, "overlap_pct": 100.0}
```

**954.9 s → 153.7 s, 6.2×.** The clock is the least important number there:
`overlap_pct: 100.0` is the correctness gate — all 300 review_ids match the set
the slow path produced, so this is the same data arriving sooner, not a shorter
scrape. Zero Chrome processes survived.

Round trips per 30-iteration / 300-review run:
| | before | after |
|---|---|---|
| full-DOM dedup rescan | ~4,650 | 30 |
| per-card parsing | ~12,600 | 60 |
| idle tail iterations | 25 | 3 |

Two design assumptions were caught by measurement rather than review:
- **`vtext` is not `innerText`.** Graded against ChromeDriver's `WebElement.text`
  over 59 elements: 6 mismatches (non-rendered elements, U+200B, `<p>` spacing,
  table cells, whitespace-only lines, NBSP). The proposed `\n{2,}`→`\n` collapse
  would itself have corrupted `<br><br>`. Rewritten empirically to 113 elements
  / 0 mismatches.
- **`grew = height > last_height` had a hole** — three shrinking iterations
  would have falsely exhausted the pane (Google virtualising off-screen cards).
  Now `changed = height != last_height or cards != last_cards`. Found by a
  mutation that refused to go red.

Exhaustion is conservative by construction: no-fresh AND unchanged AND not-busy
AND at-bottom, for ≥3 iterations **and** ≥3.0 s wall-clock; missing metrics carry
the previous values forward rather than writing back a zero nothing measured; and
the pre-existing `idle >= max_idle` bound survives as the backstop. The batched
path falls back to the original per-card loop on any script failure, with a
circuit breaker (3 consecutive failures, or 30% of cards falling back).

Verification, independently re-run rather than taken from the report:
- equivalence fixture: **35 checks, 0 failures**, `review_id` byte-identical,
  42 payload fields and 3 full cards identical between paths;
- vendor suite unchanged in failures (3 failed / 8 errors, pre-existing and
  identical before and after) and +74 new tests;
- the patch applied to a **clean upstream clone** (09bfa62), pulling in
  `modules/dom_batch.py` and parsing;
- placeintel suite 251 OK.

# RESIDENTIAL PROXY — now live on prod

Credential installed into `/opt/gmr/app/.env` (mode 640, `root:placeintel`) from
the local 1Password-backed cache, piped over ssh stdin so the value never
appeared in a terminal, a log, or an argv. Verified from the box:

```
prod direct egress : 62.171.132.182          <- the datacenter IP
relay egress       : 14.178.42.106  1.06s
                     14.191.22.81   1.01s    <- Vietnamese residential
                     14.232.108.76  1.24s
```

⚠️ **This value is erased by the first successful CI deploy** unless the GitHub
secret exists. `deploy-contabo.yml` regenerates `.env` wholesale, and the line it
writes is `${{ secrets.PLACEINTEL_RESIDENTIAL_PROXY_URL }}` — unset, that writes
an empty value over the working one. Actions is currently billing-blocked so
nothing will overwrite it today, but **adding the repo secret must happen before
billing is restored**, or restoring billing silently disables the proxy again.

---

# FINAL — after the adversarial review's three fixes

```json
{"returned": 300, "secs": 141.0, "s_per_review": 0.47,
 "baseline_secs": 954.9, "speedup_x": 6.77,
 "scraper_rows_after": 300, "overlap_with_previous_ids": 300, "overlap_pct": 100.0}
```

**954.9 s → 141.0 s, 6.8×**, still with a 100% identical review-id set and zero
surviving Chrome. Note it got *faster* than the 153.7 s first measurement: fixing
`_wait_for_growth`'s baseline means the loop now waits for Google to deliver the
next batch instead of spinning through barren passes.

## What the adversarial review caught that testing had not

| # | Finding | Why it mattered | Now gated by |
|---|---|---|---|
| 1 | The cited parity harness **did not exist in the repo** — all 74 tests drove a `_FakeDriver` and executed zero JS | `vtext` is a 75-line hand port feeding the content hash; one divergence marks every review `changed` on every run, forever | `tests/test_dom_batch_parity.py`, real headless Chrome, 67 elements / 0 mismatches, asserts its own denominator |
| 2 | `likes` became a stated **0** on a stale like-button | Pre-change the exception escaped and the card was skipped; now a wrong number reached the DB and flipped `engagement_hash`. Absent is not zero | `TestStaleLikeButtonIsNotZero` |
| 3 | `_wait_for_growth` seeded from the **previous** pass's pane size | Its first poll always exceeded the stale baseline, so it returned `True` having waited for nothing — the feature that replaced the fixed sleeps was a no-op | `TestGrowthWaitBaseline` (source-level; the predicate is decidable, the loop is not exercisable offline) |

The measurement for #1 *had* been done — in a scratch directory that does not
survive the session, which is the same as not having it. That is the lesson worth
keeping: **evidence that is not in the repo is not evidence.**

Two process notes:
- A restored file kept reporting RED until `__pycache__` was cleared. Mutation
  harnesses must run under `-B` / `PYTHONDONTWRITEBYTECODE=1`, or they measure
  the bytecode cache rather than the source.
- The patch generator swept in Baidu cloud-sync turds
  (`.scraper.py.baiduyun.uploading.cfg`) via a `'*.cfg'` filter entry and the
  patch then conflicted on the server. Prod was reset to clean stock upstream and
  re-patched. The filter is now narrow and excludes dot-files, and `'*.html'` was
  added — without it the parity test shipped without the fixture it needs.

Vendor suite: **397 passed, 0 failed** (was 3 failed / 317 passed), 8 pre-existing
s3/mongo config errors unchanged. placeintel suite 251 OK.

---

# E5 — capture the REAL `listugcposts` request format (2026-08-31, follow-up)

**Why a new experiment rather than another guess.** E2 tried five hand-built `pb=`
variants and got HTTP 403 from three different egress classes. Identical rejection
from datacenter and residential says *format*, not policy — so a sixth guess has the
same prior as the first five. The only instrument that settles it is a live browser
on the path that already works.

**Why the previous instrumentation saw nothing.** E2's note ("the page issues no
`/maps/rpc/` request that either a fetch/XHR hook or resource timing observes") has
two candidate explanations, and both are instrument defects rather than findings:

1. The hook was installed **after** page load. Google Maps captures pristine
   `XMLHttpRequest` / `fetch` references during its own bootstrap; a hook applied
   later patches an object nobody uses. Fix: install via CDP
   `Page.addScriptToEvaluateOnNewDocument`, which runs before any page script.
2. `performance.getEntriesByType('resource')` is capped by
   `resourceTimingBufferSize`, **default 250 entries**. Google Maps blows past 250
   in the first second, so everything after that is silently dropped. Fix: an
   unbuffered `PerformanceObserver`, which has no cap.

**Instruments (deliberately redundant).**
- chromedriver CDP performance log (`log_cdp_events=True` →
  `driver.get_log("performance")`) — browser-level `Network.requestWillBeSent`,
  sees every request whatever the page does, including POST bodies.
- In-page hooks on XHR / fetch / sendBeacon / WebSocket + unbuffered
  `PerformanceObserver`, installed pre-document.

**Windowed capture.** Everything before the first scroll is discarded. The
pagination request then has to stand out against ~0 noise instead of ~800 initial
requests. The window is only valid if the card count actually grew — recorded as
`window_is_valid`, because a window that loaded no new reviews proves nothing.

Harness: `/tmp/capture_rpc.py` on prod (local egress to google.com is blocked —
`curl https://www.google.com` returns 000 after 20 s). Run detached under `setsid`
so a tool timeout cannot orphan the Chrome tree.

## Result — `listugcposts` is not the endpoint any more

Three runs. The first two were instrument failures and are recorded because they
are the reason to distrust E2's "saw nothing":

| run | outcome | why |
|---|---|---|
| v1 | crashed | my bug — `"return " + RESET` where RESET already contains `return` |
| v2 | **window invalid** | 6 cards, delta 0. `click_reviews_tab` alone leaves the Overview pane (a few teaser reviews, no pagination). Its 17 captured requests proved nothing. |
| v3 | **valid** | `set_sort(driver,'newest')` is the step that swaps in the real reviews list. 20 cards → warm-up 20→40 → recorded window 40→60. |

v2 is the whole lesson: a capture window over a pane that never paginates looks
exactly like "the request does not exist". `window_is_valid` (did the card count
grow?) is now asserted, not assumed.

### What the valid window contained
88 requests. Stripping telemetry (`/maps/preview/log204` ×9 and `/gen_204` ×3 —
all HTTP 204, `image/gif`), avatar images from `lh3.googleusercontent.com`, blob
URLs and one map tile, **exactly one** request carries review data:

```
POST https://www.google.com/maps/_/MapsWizUi/data/batchexecute
     ?rpcids=qv9Egd&source-path=<place path>&hl=en&_reqid=<n>&rt=c
```

`200`, `application/json`, initiator `script`, type XHR.

**Zero `/maps/rpc/listugcposts` requests. Zero `/maps/rpc/` of any kind.**

So E2's 403 was never a format guess that missed by a detail — the endpoint
those five variants probed is not what the current Maps front-end calls. Reviews
moved to the generic `batchexecute` RPC transport, and a GET to the old path is
answered 403 whatever the `pb` string says. That also explains why the 403 was
byte-identical from datacenter and residential IPs: nothing about the request was
ever going to work.

### The request, decoded
Request headers that are not standard browser furniture:

| header | value |
|---|---|
| `Content-Type` | `application/x-www-form-urlencoded;charset=UTF-8` |
| `X-Same-Domain` | `1` |
| `X-maps-bgkey` | BotGuard token, `!` + ~1.5 KB of base64 (value redacted) |
| `x-maps-diversion-context-bin` | `CAE=` |

Body (`f.req`, URL-decoded, whitespace added):

```jsonc
[[["qv9Egd",
  "[[[\"0x314a443465a12319:0x5daa3b5a1ada17ce\"],   // ← feature id, not place_id
     null,null,null,null,[null,null,null,[[1],[3]]]],
    [10,\"CjEIARIpCgoAP72GB22XzZ__EhC…GACIA:20\"],  // ← [page size, cursor:offset]
    null,null,
    [\"hGGVatzuEI2ukdUPqaeM8As\",null,null,null,null,null,81],  // ← page `ei` token
    null,null,
    [null,1,1,null,1,null,1,null,null,null,null,[1,1,null,[[1]]]],
    null,null,[3,1,null,null,null,[2]],null,[2]]",
  null,"generic"]]]
```

Readable parts:
- **`rpcid = qv9Egd`** — the reviews RPC.
- **feature id** `0x…:0x…` (the hex pair), *not* the `ChIJ…` place_id.
- **`[10, "<cursor>"]`** — page size 10 and an opaque cursor whose suffix (`:20`)
  is the offset already consumed. This is the pagination handle.
- **`ei` token** `hGGVatzuEI2ukdUPqaeM8As` — page-scoped, also present in the
  `log204` telemetry, so it is minted per page load.
- No `at=` XSRF token — consistent with an unauthenticated read.

### Still open at this point
Which of those headers is load-bearing. `X-maps-bgkey` is a BotGuard product; if
it is required, a browser-free walk needs to mint one, which is a different and
much larger problem than formatting a URL. E6 ablates one header at a time
against a known-good request rather than concluding from the full set.

---

# E6 — which parts of the captured request are load-bearing?

Method: capture a live `qv9Egd` batchexecute, replay it verbatim from `requests`
with the browser's cookies, confirm that works, **then remove exactly one thing per
call** against that known-good baseline. Copying the whole header set and declaring
victory says nothing about which part mattered — and `X-maps-bgkey` is a BotGuard
token, so "is it required?" is the question that decides whether a browser-free walk
is even possible.

## The result that changes how every other row must be read

**Every single variant returned HTTP 200 — including the ones that failed.**
Failure is a ~170-byte empty envelope, not an error status. A client that checks
`r.raise_for_status()` and moves on would report success while returning nothing,
forever.

| variant | status | review ids | response bytes |
|---|---|---|---|
| **full (baseline)** | 200 | **10** | 36,852 |
| drop `X-Same-Domain` | 200 | 10 | 36,852 |
| drop `x-maps-diversion-context-bin` | 200 | 10 | 36,849 |
| drop `Referer` | 200 | 10 | 36,853 |
| **drop `X-maps-bgkey`** | 200 | **0** | 169 |
| **drop cookies** | 200 | **0** | 174 |
| **drop browser `User-Agent`** | 200 | **0** | 173 |
| `Content-Type` only | 200 | **0** | 171 |
| `Content-Type` + UA, no cookies | 200 | **0** | 173 |

So the minimal working request is:

```
POST https://www.google.com/maps/_/MapsWizUi/data/batchexecute?rpcids=qv9Egd&…&rt=c
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
User-Agent:   <a real browser UA>
X-maps-bgkey: <BotGuard token, ~180 chars, minted per page load>
Cookie:       NID, SOCS, AEC, SEARCH_SAMESITE, __Secure-STRP
f.req=…
```

`X-Same-Domain`, `Referer` and `x-maps-diversion-context-bin` are decoration.

## What this means

`X-maps-bgkey` being required is the whole story for feasibility. It is produced by
BotGuard JS running in a real page, so **there is no browser-free cold start** — the
endpoint cannot replace the browser, only the *scrolling*. The viable shape is
bootstrap-then-walk: one browser page load to mint `bgkey` + cookies + the `ei`
token, then plain HTTP for the pages. Whether that walk actually advances is E7;
until it does, this is a working single request, not a paginator.

## A defect in my own instrument, recorded because it changes what the numbers mean
The in-browser control replay reported 200 / 0 ids and I nearly read it as "the
captured request is wrong". It was not: my in-page `fetch()` hard-coded only
`Content-Type` and `X-Same-Domain` and therefore omitted `X-maps-bgkey` — the
control failed for exactly the reason the ablation table identifies. It is a
consistent result, not a contradictory one, but only because the ablations existed
to explain it. `payload_bytes: 0` in the same run is a real parser bug (the
length-prefixed chunk walk did not find the `wrb.fr` frame); id counts came from a
regex over the raw text, which is why they are still trustworthy. Both are fixed in
E7.

---

# E7 — is the cursor walkable off-browser? **YES**

The question E6 left open. A single working request is not a paginator: a cursor
that is *accepted and ignored* returns a healthy-looking 10 reviews every time, and
that failure is indistinguishable from success unless the ids are diffed. So this
asserts **disjointness**, not non-emptiness.

## Two parser bugs found first, both in my own code
Recorded because the first walk attempt reported `0 review ids` from a response that
was completely fine, and "the request stopped working" was the obvious wrong read.

1. **The `batchexecute` length prefix is not a usable byte count.** The frame header
   said `36757` for a body that is 36,852 chars / 36,890 bytes; slicing by that
   number as *characters* over-ran the frame, and slicing by it as *bytes*
   truncated mid-string. Fix: ignore the prefixes and walk the stream with
   `json.JSONDecoder().raw_decode()`.
2. **Review ids are not `Ch…`.** They are `Ci9DQUlRQUNvZENodHlj…` — and the `Cht…`
   form an earlier regex matched is that same id *base64-decoded*, which exists in
   the response only incidentally. The id to key on is the one the DOM also
   carries in `data-review-id`, so DOM and RPC are directly comparable.

The tell for both was `payload_bytes: 36852` sitting next to `n_ids: 0`. A response
that large is not a rejection.

## Walk result — measured, browser closed before the first request

| | |
|---|---|
| pages | 20 |
| reviews returned | 10 per page, **200 total** |
| **new on every page** | **10/10 — zero overlap, all 20 pages** |
| cursor | advances `:20 → :30 → … → :210`, exactly as the offset suffix claims |
| wall clock | **9.7 s** for 200 reviews (0.12–0.32 s per request) |
| authors parsed | 200/200 |
| text present | 166/200 (the rest are rating-only reviews, which is normal) |
| rating histogram | `{1:3, 2:1, 3:2, 4:2, 5:192}` |

`bgkey` survived all 20 requests, and the browser was `quit()` before the first one
— so the token is a portable string, and the walk is genuinely browser-free once
bootstrapped.

## Page size: honoured up to 20, then rejected (not clamped)

| requested | returned | bytes |
|---|---|---|
| 10 | 10 | 36,889 |
| **20** | **20** | 83,264 |
| 50 | **0** | 139 |
| 100 | **0** | 139 |
| 200 | **0** | 138 |

Worth stating plainly because the failure is again an HTTP 200 with an empty
envelope. A client that assumed "bigger is at worst clamped" and asked for 100
would return zero reviews and report success.

## Field map (verified against the payload, not guessed)

| field | path in each review record |
|---|---|
| review id | `[0][0]` (same value as DOM `data-review-id`) |
| **rating** | `[0][2][0][0]` |
| text | `[0][2][15][0][0]` |
| author name | `[0][1][4][5][0]` |
| author id | `[0][1][4][5][3]` |
| author avatar | `[0][1][4][5][1]` |
| relative date | `[0][1][6]` (e.g. `"4 weeks ago"`) |
| absolute timestamp | `[0][1][2]` / `[0][1][3]` (µs since epoch) |
| photos | `[0][2][2][*][1][6][0]` |

Rating was identified by discrimination, not position-guessing: across the 10
reviews of page 0 the path yields `[5,5,5,5,5,5,3,5,5,5]`, and index 6 is the one
review whose text complains that "price was deceiving". A path that merely returned
all-5s on a 5.0-rated place would not have been evidence.

---

# E8 — is the RPC returning the RIGHT place's reviews? **YES** (and a separate defect fell out)

Before trusting any of this, the data has to be checked against something that is
not itself. Two cross-checks, one of which failed and needed explaining.

## Cross-check 1 — prod's app database: **disagrees**, 3 of 291 texts in common
`placeintel.db` holds 314 reviews for this place from a DOM scrape at 07:46 UTC the
same morning. Against the RPC's 1,385:

| comparison | overlap |
|---|---|
| review ids (after stripping the app's `gsp:` prefix) | 3 / 314 |
| author names | 9 / 314 |
| review texts | **3 / 291** |

Both sources record the same place name, the same coordinates
(`20.72468, 107.0520345`) and the same feature id prefix, and the app's reviews talk
about "Mr. Tung" while the RPC's talk about "Yen". Two different review sets.

## Cross-check 2 — the DOM and the RPC, same page, same instant: **exact match**
Comparing scrapes taken hours apart cannot say which source is wrong. Loading the
page once and asking both instruments about *that* page can:

| | |
|---|---|
| review-id overlap | **10 / 10** |
| author overlap | **10 / 10** |
| feature id in the captured request | `0x314a443465a12319:0x5daa3b5a1ada17ce` (the target) |

So the RPC returns exactly what the page is displaying, for the correct place. The
RPC path is verified; the 07:46 app rows are the anomaly.

## The fallout — a pre-existing defect, NOT caused by anything here
**Status: UNEXPLAINED. Recorded, not diagnosed.** Something caused that morning's
DOM scrape to store 311 reviews that are not this place's. The plausible mechanism
is that the vendor's bypass navigates by *name search*
(`/maps/search/<name>/@lat,lng,17z`) and Cát Bà has many similarly-named rental
shops, so the first result is not guaranteed to be the requested listing — but that
is a hypothesis, and it should not be written down as a cause without its own
experiment. What can be said now:

- It is independent of this work; the app rows predate every experiment here.
- It is exactly the fragility the RPC path does not have: the RPC addresses a place
  by **feature id**, so there is no name-matching step that can silently land
  elsewhere.
- **A DOM scrape that lands on the wrong listing is silent.** It reports
  `reviews_found: 300, status: completed` and writes them under the requested
  `place_id`. Nothing in the pipeline compares what it fetched against what it asked
  for. That is worth a guard regardless of the mechanism.
- One more datum, pointing the same way: the RPC's newest review for this place is
  dated **2026-08-02**, while the app rows contain reviews dated up to
  **2026-08-24**. The DOM was sorted newest and matched the RPC 10/10, so the page
  for `0x314a443465a12319:0x5daa3b5a1ada17ce` genuinely has nothing newer than early
  August — and the app's late-August reviews therefore belong to something else.
  Strongly suggestive; still not a demonstrated mechanism.

---

# DELIVERED

| artifact | what it is |
|---|---|
| `placeintel/maps_rpc.py` | parser + cursor walker for the `qv9Egd` RPC (stdlib only, no network) |
| `tests/test_maps_rpc_contract.py` | 20 tests, all three key ones mutation-verified RED→GREEN |
| `tests/fixtures/maps_rpc_qv9Egd_page.txt` | a REAL captured response, redacted (the mirror repo is public) but keeping the stale length prefix, multibyte text, both id namespaces and the discriminating rating spread |
| `scripts/maps_rpc_probe.py` | bootstrap-then-walk, the end-to-end exercise of the module |

Suite: **271 tests OK** on the project venv (was 251).

## Measured cost, reference place (1,395 reviews on Google)

Measured through `scripts/maps_rpc_probe.py`, i.e. the committed module, not the
scratch scripts that discovered the format:

| path | reviews | wall clock | per review |
|---|---|---|---|
| DOM scroll, as shipped in v0.4.79 | 300 (the configured cap) | 141 s | 0.47 s |
| **bootstrap + RPC walk** | **1,385** | **68.3 s + 15.2 s = 83.5 s** | **0.060 s** |

```json
{"bootstrap_secs": 68.3, "walk_secs": 15.2, "pages": 70, "reviews": 1385,
 "secs_per_review": 0.0603, "with_author": 1385, "with_text": 1191,
 "with_rating": 1385, "mean_rating": 4.968,
 "stopped_because": "no next cursor — end of reviews",
 "missing_required_headers": []}
```

1,385 unique ids, no duplicates, reviews spanning 2022-08-05 → 2026-08-02, 152 with
photos. It ends because Google stops issuing a cursor, not because a cap was hit.

The bootstrap is a fixed ~70 s browser cost and dominates small scrapes; the walk is
~0.2 s per 20 reviews. So the win scales with place size — roughly break-even under
~150 reviews, ~6.5× per review at 1,385.

## NOT done, and deliberately so
Wiring this into `reviews.py` as a fast path is a separate decision, not a
continuation of "capture the format". It changes the product's data source to an
undocumented internal API that Google can move without notice, so it needs a
fallback to the DOM scraper, a parity gate between the two, and a call on whether
the id namespace difference (`gsp:` prefixed DOM ids vs raw RPC ids) means new rows
or updated ones. Flagged for the owner; the module and probe are ready for it.

---

## PHASE 2 — wire the RPC into `reviews.py` (2026-08-31, requested)

**Ask:** "接进 reviews.py,做 DOM 兜底和一致性校验 … or make both exist as fallback?"
**Answer: both, in a fixed order.** RPC primary → DOM (scraper-pro) fallback →
SerpAPI (paid) last. The RPC is an undocumented internal API that Google can
retire the way it retired `listugcposts`; the DOM path is the proven one and
stays as the safety net rather than being replaced.

**Target for the e2e gate:** `https://maps.app.goo.gl/W1zN6FktLeA9tK1c9?g_st=ic`
→ resolves (302) to `Vu Binh Exchange & ATM, 139 Đường 1/4, Cát Hải, Hải Phòng`
with `ftid=0x314a455ad6407235:0xe121f190cbc130e7`. Note this is a DIFFERENT place
from the E5–E8 reference (`0x314a443465a12319:0x5daa3b5a1ada17ce`).

### P2-A. Two defects found while reading the shipped code

1. **The walk starts at the captured cursor, not at the beginning.** The probe
   drains the CDP log and then scrolls to provoke a request, so the template it
   captures already carries an offset (`…:20`). `walk()` keeps that cursor, so
   everything before it is skipped. This is why E7 reported **1,385 of 1,395** —
   the ~10 missing reviews are exactly the bootstrap offset, and it reads as
   "Google returned slightly fewer" rather than as a bug. Fix: collect every
   `qv9Egd` request from page load onward and keep the one with the **smallest
   trailing `:N` offset**, rather than the last one seen.

2. **Nothing checks which listing the browser landed on.** This is the
   UNEXPLAINED finding from E8 (314 stored reviews sharing 3/291 texts with the
   real page). The RPC does not fix it by itself — it faithfully returns whatever
   feature id the captured `f.req` names. But the captured `f.req` *states* that
   feature id, and `parse_maps_url` already extracts the expected one from the
   URL's `ftid`. Comparing the two is free and decidable.

### P2-B. Consistency verification = two checks, both riding the bootstrap

Neither costs a second browser run.

| Check | Compares | On mismatch |
|---|---|---|
| **Identity** | feature id inside the captured `f.req` vs `ftid` from the place's Maps URL | reject the whole fetch, fall back to DOM |
| **Parity** | first RPC page's review ids vs `data-review-id` in the DOM of the same session | record `parity_*` diagnostics; reject only when overlap is 0 with both sides non-empty |

Identity is the strong gate (it is what makes the wrong-listing failure loud
instead of silent). Parity is the weaker one and must stay weaker: sort order and
timing can legitimately shift the window, so only a *complete* disjointness with
data present on both sides is evidence of a real problem.

### P2-C. Shape

- `placeintel/maps_rpc.py` — add pure helpers `feature_id_of(template)`,
  `normalize_feature_id`, `same_feature`, `cursor_offset`. Still no network.
- `placeintel/maps_rpc_fetch.py` — NEW. Bootstrap + walk + both checks. Lazy
  selenium import so the app can import the module without the vendor venv.
  Also runnable as `python -m placeintel.maps_rpc_fetch` under the vendor venv,
  which is how `reviews.py` invokes it.
- `placeintel/reviews.py` — `_fetch_via_maps_rpc()` before `_fetch_via_scraper_pro()`,
  reusing the existing lock / slot / process-group / timeout machinery.
- **Review id namespace stays `gsp:`** for both paths. The DOM `data-review-id`
  and the RPC review id are the same value (E8: 10/10 match), and `review_id` is
  the reviews table's primary key — so a shared prefix makes the two paths
  dedupe against each other instead of double-storing every review. The prefix
  denotes the id namespace, not the fetcher; `source` records the fetcher.
- Kill switch `PLACEINTEL_DISABLE_MAPS_RPC=1` so the RPC can be turned off in
  production without a deploy.

### P2-D. Gate

Full e2e on prod against the URL above: `/api/scout` single-shop, reviews stored,
report generated, and `source='maps-rpc'` rows present — plus the identity check
recorded as passed rather than assumed.

### E9 — the walk was enumerating the wrong list, and a German UI is why

Target: `Vu Binh Exchange & ATM` (`0x314a455ad6407235:0xe121f190cbc130e7`), the
place behind the URL in the request. Identity matched on every run; the RPC
returned 74-75 reviews and stopped with `no next cursor — end of reviews`, which
reads as completeness. It was not.

A side-by-side dump of the DOM cards against the walk, same session:

| | newest item |
|---|---|
| page's top review card | `vor einer Woche` |
| walk's first review | `vor 6 Monaten` |
| shared ids between the two | **0 of 10** |

`tabs: ["Übersicht über …", "Rezensionen zu …"]`, `sort_label: "Sortieren"`.
**The page renders in German** — the prod box egresses from a German datacenter
IP — and the vendored scraper's `set_sort(driver, "newest")` matches English
control labels only. It no-ops silently, the pane stays on *Relevanteste*, and
the captured template therefore walks Google's **relevance** list, which is a
curated subset with a genuine end. Every signal said success.

`Accept-Language` and a `PREF=hl=en` cookie do not fix it: the vendor builds its
own `maps/search/<name>/` URL internally and that navigation carries neither.
The DOM path already wraps `driver.get` to append `hl=en` for exactly this
reason; the RPC bootstrap now uses the same wrapper.

**Two corrections this forces.**

1. **Parity was demoted to a log line and has been restored as a gate.** Its
   failures were read as rendering artefacts — a 3-card sample, a virtualised
   list, a selector matching avatars as well as cards. All three of those were
   real and worth fixing, and *underneath* them the check was right the whole
   time. The rule it earns: before softening a check because its failures look
   spurious, find the mechanism. "I do not understand why it fires" is not
   evidence that it is wrong, and demoting it would have shipped six-month-stale
   reviews reported as complete.

2. **E8's conclusion is now in doubt.** That section recorded 314 stored DOM
   reviews sharing 3 of 291 texts with the RPC's view and inferred the DOM scrape
   had landed on the wrong listing. The same German-locale defect gives an
   innocent explanation: the RPC was walking the relevance subset while the DOM
   walked newest-first, so on a 1,395-review place the two would legitimately
   barely overlap. The wrong-listing hypothesis is **not disproven** — the
   name-search navigation genuinely has no identity check, which is why the
   identity guard is worth having — but it is no longer the leading explanation,
   and the follow-up task should re-test with `hl=en` forced before assuming it.

`no next cursor — end of reviews` is the server saying it has nothing more to
give *for the enumeration you asked for*. It is not a statement about the place.

### E10 — correcting E9: it is newest-ordered, it just starts 11 reviews in

E9 concluded the walk enumerates Google's *relevance* list. **That was wrong**,
and forcing `hl=en` (which E9 got right, and which is still a real fix — it is
what made the review total readable at all) did not change the symptom. The
production ladder, RPC enabled, on the target place:

```
maps-rpc …: 74 reviews, identity=match parity=no-overlap coverage=0.871 of 85
            pages=4 bootstrap=109.9s walk=0.6s
WARNING   : walked 74 of the 85 reviews Google lists (87%)
WARNING   : the reviews on screen are not in the walk (10 DOM cards, 74 walked,
            0 shared) — falling back to the DOM scraper
```

Four facts that only fit one story:

- The walk's own dates increase monotonically in age — `6 months, 6 months,
  7 months, 7 months`. A relevance ranking is not date-ordered. **The walk IS
  newest-first.**
- `85 listed − 74 walked = 11 missing`, and the captured cursor's offset is 10.
- The DOM's top cards (`a week ago` ×4, `3 weeks ago` ×2) are exactly the ones
  missing, and position ~12 of a newest-sorted 85 lands around six months old.
- `_rewind` reports success — the server accepts `<blob>:0` — and returns the
  identical 74. So **the `:N` suffix is decorative; the blob carries the
  position.** Rewriting it cannot reach the start.

So the mechanism is: **Maps renders the first ~10 reviews from data embedded in
the page, and the first RPC call it makes is already at offset 10.** There is no
position-0 request to capture, because the page never needs one. The walk is
correct and complete *from where it starts*, and the reviews it cannot reach are
the newest ones — the ones that matter most.

Two things this validates and one it opens.

- **`coverage` against Google's stated total is the right check.** It put a
  number on the gap (87%) without any theory about the cause, on the first run
  it was available.
- **Parity earned its place as a gate**, twice: it refused this data, and its
  refusal is what forced the measurement. Both checks agreed independently.
- **The fix is to merge, not to seek.** The unreachable head is already on screen
  — the vendored `modules/dom_batch.py` extracts exactly those cards in one round
  trip. Parse the embedded first page from the DOM and concatenate it with the
  walk; `coverage` then becomes the gate on whether the merge is complete. That
  is the next piece of work, and until it lands the RPC stays opt-in.

---

## E11 — the head merge, and what it closed (v0.4.82, 2026-08-31)

E10 said the fix was to merge the on-screen head rather than hunt for a
position-0 cursor. Building it closed the two cheaper alternatives, so neither
needs revisiting:

| hypothesis | verdict | evidence |
|---|---|---|
| the head is embedded as a reusable RPC payload | **no** | the rendered page HTML holds **0** occurrences of `qv9Egd` and no `AF_initDataCallback`; the head exists only as DOM |
| a sibling rpcid serves reviews 0-9 | **no** | the page also calls `hspqX` x2, `T4jwAf` x2, `r4skrb` x1 — none moves `qv9Egd`'s earliest offset off 10 |
| rewriting the cursor to `<blob>:0` reaches the head | **no** (already known) | accepted, returns the identical rows |

So the head is read from the DOM through the vendor's own `modules/dom_batch.py`
and `RawReview.from_payload` — the file that already owns every review selector
in this codebase — and concatenated.

**Measured, through the deployed API (`POST /api/shop`, job `01f0f34520ee`):**

```
maps-rpc 0x314a455ad6407235:0xe121f190cbc130e7: 85 reviews (10 on screen + 75 walked),
  identity=match contiguity=contiguous coverage=1.0 of 85 pages=4
  bootstrap=100.6s walk=0.5s
[reviews] 85 条评价（新增 0 条）   → 1 report, errors: []
```

The DOM scraper did not run at all. `新增 0 条` is the cross-check worth keeping:
all 85 ids deduped against the 85 the DOM scraper had stored earlier, so the two
paths agree at id level on the whole set.

**Speed, honestly.** 101 s here against the DOM scraper's **170 s** measured on
the same place earlier the same session (17:29:22 → 17:32:12). That is a modest
win, and it is the wrong place to look: the cost is a near-fixed bootstrap plus
~0.5 s per 100 reviews, so 1,385 reviews walk in 15.2 s. It is the tail that
pays, and the ratio should never be quoted from one place.

### Gates: one retired, two added

`parity`'s `no-overlap` rule blocked when nothing on screen appeared in the walk.
It was a true positive every time it fired — but the cause was *structural*, the
walk starting at offset 10 while the pane showed 0-9. Merging the head makes
disjointness the healthy shape, so the rule would now refuse every correct run.
Retired to a diagnostic, and replaced by two exact checks:

- **contiguity** — `gap = max(0, start_offset - unique_ids_in_head)`. Counting
  *unique* ids matters: the DOM yields two `div[data-review-id]` per card, and an
  inflated denominator is the one way this gate passes while wrong.
- **coverage** — merged total vs the count read off the page, an observer
  independent of the walk. Floor `PLACEINTEL_MAPS_RPC_MIN_COVERAGE` (0.95).

### Defects found on the way

- The vendored date converter never handled hours/minutes/"just now" although its
  docstring claimed `"an hour ago"` worked — so every review under a day old got
  no date, on the **DOM path too**. Undated rows sort last under
  `review_date or ""` and are capped first: exactly the newest reviews.
- Those datetimes are naive UTC, read with `.timestamp()` (local). Prod is CEST.
- The cursor rewind could not observe its own result — it checked only that the
  request answered, and the server answers `<blob>:0` with the same rows.
- `scripts/maps_rpc_probe.py` was a second browser bootstrap with no identity
  check, and the entry-point contract test was pointed at *it* rather than at the
  worker. Deleted; one entry point.
- `vendor/.../tests/fixtures/reviews_fixture.html` carried real reviewers' avatar
  URLs, contributor ids and names into the tracked patch, one push from a public
  repo. Scrubbed; the hygiene gate now covers `vendor-patches` too.

### Open

- A place Google lists at 85 holds **369** stored rows, all `scraper-pro`, and the
  report says "369 analyzed". Either Google removed reviews over three years or an
  earlier name-search scrape landed on another listing. The DOM path still has no
  identity check.
