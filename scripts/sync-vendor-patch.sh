#!/usr/bin/env bash
# Capture the vendored scraper's local modifications into a tracked patch.
#
# `vendor/` is gitignored and the deploy rsync skips it, so without this the
# patches live only as dirty working-tree state on whichever machines happen to
# have them — invisible to review, un-restorable after a reset, and enough to
# make `git pull --ff-only` in remote-bootstrap.sh abort. Run this after every
# change to vendor/, and commit the result.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vendor="$root/vendor/google-reviews-scraper-pro"
out_dir="$root/vendor-patches"
out="$out_dir/google-reviews-scraper-pro.patch"

if [ ! -d "$vendor/.git" ]; then
  echo "No vendor clone at $vendor" >&2
  exit 1
fi

mkdir -p "$out_dir"

# Record the upstream commit the patch is cut against. `git apply --3way` can
# absorb small upstream drift, but a reader needs to know the baseline to judge
# whether a conflict means "rebase the patch" or "upstream changed underneath us".
base="$(git -C "$vendor" rev-parse HEAD)"
base_desc="$(git -C "$vendor" log -1 --format='%h %s' HEAD)"

# A patch of MODIFIED files only is a trap: our changes add new modules, and
# `modules/scraper.py` imports them. Ship the modifications without the new file
# and the bootstrap applies a patch that makes the scraper fail at import.
# Measured 2026-08-31: the first run of this script captured 2 files and silently
# dropped `modules/dom_batch.py`, which the other two import.
#
# So stage untracked SOURCE files with `--intent-to-add` so `git diff` sees them,
# while still excluding the junk that accumulates in a vendor checkout
# (databases, caches, cloud-sync turds, venvs). `.gitignore` already covers most
# of it; `--exclude-standard` honours it.
tmp_index="$(mktemp -t vendorpatch)"
trap 'rm -f "$tmp_index"' EXIT INT TERM
cp "$vendor/.git/index" "$tmp_index"

# Extensions only, and NEVER dot-files. Measured 2026-08-31: a '*.cfg' entry
# swept in Baidu cloud-sync turds named `.scraper.py.baiduyun.uploading.cfg`,
# which then landed in the patch and made it conflict on the server. The
# filename filter is the denominator here — keep it narrow and visible.
untracked="$(GIT_INDEX_FILE="$tmp_index" git -C "$vendor" ls-files --others --exclude-standard \
  -- '*.py' '*.yaml' '*.yml' '*.toml' '*.md' '*.html' \
  | grep -v -e '/\.' -e '^\.' || true)"
if [ -n "$untracked" ]; then
  echo "Including untracked source files:"
  printf '  %s\n' $untracked
  # shellcheck disable=SC2086
  GIT_INDEX_FILE="$tmp_index" git -C "$vendor" add --intent-to-add -- $untracked
fi

{
  printf '# Vendored scraper patch for place-intel.\n'
  printf '# Cut against upstream: %s\n' "$base_desc"
  printf '# Base commit: %s\n' "$base"
  printf '# Regenerate with: scripts/sync-vendor-patch.sh\n'
  printf '#\n'
  # Modified tracked files PLUS new source files, via the throwaway index above
  # so the real index is never touched.
  GIT_INDEX_FILE="$tmp_index" git -C "$vendor" diff HEAD --binary -- .
} > "$out"

lines="$(GIT_INDEX_FILE="$tmp_index" git -C "$vendor" diff HEAD --numstat -- . | wc -l | tr -d ' ')"
if [ "$lines" -eq 0 ]; then
  echo "No local vendor modifications — wrote a header-only patch to $out" >&2
else
  echo "Captured $lines modified file(s) into $out"
fi

# Prove the artifact is usable before anyone relies on it. A patch that does not
# apply to the tree it was cut from is a patch that will fail on the server, at
# deploy time, with no way back.
if ! GIT_INDEX_FILE="$tmp_index" git -C "$vendor" apply --check --reverse "$out" 2>/dev/null; then
  echo "WARNING: the captured patch does not reverse-apply to the current tree." >&2
  echo "         Inspect $out before committing it." >&2
  exit 1
fi
echo "Verified: patch reverse-applies cleanly to the current vendor tree."
