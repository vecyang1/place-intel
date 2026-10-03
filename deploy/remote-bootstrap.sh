#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="${PLACEINTEL_DEPLOY_DIR:-${GMR_DEPLOY_DIR:-/opt/placeintel}}"
APP_DIR="$DEPLOY_DIR/app"
ENV_FILE="$APP_DIR/.env"
SERVICE_NAME="placeintel"
RUN_USER="placeintel"
VENDOR_DIR="$APP_DIR/vendor/google-reviews-scraper-pro"

if [ "$(id -u)" -ne 0 ]; then
  echo "remote-bootstrap.sh must run as root" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${GOOGLE_API_KEY:?GOOGLE_API_KEY is required}"
: "${VECTORENGINE_API_KEY:?VECTORENGINE_API_KEY is required}"

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  ca-certificates curl git gnupg python3 python3-pip python3-venv wget

if ! command -v google-chrome >/dev/null 2>&1; then
  install -d -m 0755 /etc/apt/keyrings
  wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /etc/apt/keyrings/google-linux.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    >/etc/apt/sources.list.d/google-chrome.list
  apt-get update
  apt-get install -y google-chrome-stable
fi

if ! id -u "$RUN_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$DEPLOY_DIR" --shell /usr/sbin/nologin "$RUN_USER"
fi
if getent group docker >/dev/null 2>&1; then
  usermod -aG docker "$RUN_USER" || true
fi

install -d -m 0755 "$APP_DIR/data" "$APP_DIR/vendor"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR/data"
chown "root:$RUN_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

# The vendored scraper is an upstream clone that we PATCH. `vendor/` is
# gitignored and rsync skips it, so before this block the patches existed only
# as dirty working-tree state on whichever machines happened to have them — and
# `git pull --ff-only` against a dirty tree aborts, so a bootstrap on a patched
# box failed rather than updating. Track the patch in-repo and re-apply it every
# time, so the vendor state is reproducible from a clean clone.
VENDOR_PATCH="$APP_DIR/vendor-patches/google-reviews-scraper-pro.patch"

if [ -d "$VENDOR_DIR/.git" ]; then
  git -C "$VENDOR_DIR" reset --hard HEAD || true
  git -C "$VENDOR_DIR" clean -fdx || true
  if ! git -C "$VENDOR_DIR" pull --ff-only; then
    rm -rf "$VENDOR_DIR"
  fi
fi

if [ ! -d "$VENDOR_DIR/.git" ]; then
  rm -rf "$VENDOR_DIR"
  git clone --depth 1 https://github.com/georgekhananaev/google-reviews-scraper-pro.git "$VENDOR_DIR"
fi

# Ensure working tree is completely pristine before applying patch
git -C "$VENDOR_DIR" reset --hard HEAD
git -C "$VENDOR_DIR" clean -fdx

if [ -f "$VENDOR_PATCH" ]; then
  echo "Applying vendor patch: $VENDOR_PATCH"
  # --3way so an upstream change that moves context still applies where it can,
  # and fails loudly where it cannot rather than silently leaving the scraper
  # on unpatched upstream code.
  if ! git -C "$VENDOR_DIR" apply --3way --whitespace=nowarn "$VENDOR_PATCH"; then
    echo "vendor patch did not apply — refusing to deploy an unpatched scraper" >&2
    exit 1
  fi
else
  echo "No vendor patch at $VENDOR_PATCH — running stock upstream scraper" >&2
fi

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/pip install -e ".[web]"

python3 -m venv "$VENDOR_DIR/.venv"
"$VENDOR_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
(
  cd "$VENDOR_DIR"
  "$VENDOR_DIR/.venv/bin/python" - <<'PY'
import pathlib
import subprocess
import sys
import tomllib

deps = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["dependencies"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *deps])
PY
)

cat >/etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=placeintel Google Maps review intelligence
Wants=network-online.target docker.service
After=network-online.target docker.service

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
SupplementaryGroups=docker
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=HOME=$DEPLOY_DIR
Environment=PLACEINTEL_PORT=9618
ExecStart=$APP_DIR/.venv/bin/placeintel-web
Restart=always
RestartSec=5
TimeoutStopSec=20
# A scrape is a headless Chrome tree: ~13 processes and ~0.8-1.2 GB RSS each,
# measured. Before these limits, four abandoned trees reached 4.7 GB on a 12 GB
# box with swap at 74% while systemd reported the service at 82 MB, because the
# browsers had escaped the cgroup as PPid-1 orphans.
#
# KillMode=control-group already reaps the cgroup on stop; the orphan leak was
# fixed in placeintel/reviews.py by giving the scraper its own process group.
# These limits are the backstop for when that fix is not enough: MemoryMax caps
# the blast radius at a value that still leaves the box responsive, and
# MemoryAccounting makes the number visible in \`systemctl status\` instead of
# hiding outside the unit.
MemoryAccounting=yes
MemoryHigh=5G
MemoryMax=6G
TasksMax=4096

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"
systemctl restart "$SERVICE_NAME.service"

for _ in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:9618/api/meta >/dev/null; then
    systemctl --no-pager --full status "$SERVICE_NAME.service" | sed -n '1,12p'
    exit 0
  fi
  sleep 0.5
done

journalctl -u "$SERVICE_NAME.service" -n 80 --no-pager >&2 || true
exit 1
