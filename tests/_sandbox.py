"""Point DATA_DIR at a disposable directory for the whole test process.

`PLACEINTEL_DATA_DIR` is a *location* variable, not a credential. Unsetting it
does not mean "use nothing" — it means "use the default", which is the
developer's real `data/` holding `placeintel.db` and `scraper_pro_reviews.db`.
Any test that takes a scrape lock, or that a future change teaches to write,
would then touch live data.

One owner per process: import this module (never re-implement it per file) and
Python's import cache does the deduplication. Import it BEFORE any `placeintel`
module, because `config.DATA_DIR` is resolved at import time — the reassignment
below is a belt-and-braces fallback for a test file that gets the order wrong,
not a licence to.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# A `spawn`ed child re-imports this module. It must land on the SAME sandbox as
# its parent — a fresh mkdtemp per process would give the two of them different
# lock directories, and a cross-process lock test would then pass trivially
# while locking nothing. The marker travels through the inherited environment;
# it is deliberately not PLACEINTEL_DATA_DIR itself, so a developer's real
# DATA_DIR (from .env or the shell) can never be mistaken for a sandbox.
_MARKER = "PLACEINTEL_TEST_SANDBOX_DIR"
_inherited = os.environ.get(_MARKER)
_IS_OWNER = _inherited is None

SANDBOX_DIR = Path(_inherited) if _inherited else Path(
    tempfile.mkdtemp(prefix="placeintel-tests-")
)
os.environ[_MARKER] = str(SANDBOX_DIR)
os.environ["PLACEINTEL_DATA_DIR"] = str(SANDBOX_DIR)

# If placeintel.config was already imported by an earlier test file, its
# module-level DATA_DIR is already bound to the real path. Rebind it.
_config = sys.modules.get("placeintel.config")
if _config is not None:
    _config.DATA_DIR = SANDBOX_DIR
    _config.DB_PATH = SANDBOX_DIR / "placeintel.db"
    _config.SETTINGS_PATH = SANDBOX_DIR / "settings.json"


def real_data_dir() -> Path:
    """Where the tests must NOT have written. Used by the isolation assertion."""
    return Path(__file__).resolve().parent.parent / "data"


def _cleanup() -> None:
    shutil.rmtree(SANDBOX_DIR, ignore_errors=True)


# Only the process that created the sandbox removes it. A child exiting first
# would otherwise delete the directory its parent is still testing against.
if _IS_OWNER:
    atexit.register(_cleanup)
