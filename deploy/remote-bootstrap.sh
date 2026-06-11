#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="${GMR_DEPLOY_DIR:-/opt/gmr}"
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

if [ ! -d "$VENDOR_DIR/.git" ]; then
  rm -rf "$VENDOR_DIR"
  git clone --depth 1 https://github.com/georgekhananaev/google-reviews-scraper-pro.git "$VENDOR_DIR"
else
  git -C "$VENDOR_DIR" pull --ff-only
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
