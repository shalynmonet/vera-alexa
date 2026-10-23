#!/usr/bin/env bash
# Pulls the latest code and restarts the Vera services. Run from inside
# the repo on the server, as root (or with sudo):
#   cd /opt/vera && sudo bash deploy/update.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER=vera

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root (sudo bash deploy/update.sh)." >&2
  exit 1
fi

echo "==> Pulling latest code"
cd "$REPO_DIR"
sudo -u "$APP_USER" git pull --ff-only

echo "==> Installing any new/updated dependencies"
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "==> Installing ffmpeg (converts Family Cheer recordings to one universal format)"
  apt-get update -qq
  apt-get install -y -qq ffmpeg
else
  echo "==> ffmpeg already installed"
fi

echo "==> Re-installing systemd units (in case they changed) and the Caddyfile"
cp "$REPO_DIR"/deploy/vera-mcp.service "$REPO_DIR"/deploy/vera-web.service \
   "$REPO_DIR"/deploy/vera-demo-reset.service "$REPO_DIR"/deploy/vera-demo-reset.timer \
   /etc/systemd/system/
if [[ "$REPO_DIR" != "/opt/vera" ]]; then
  sed -i "s#/opt/vera#$REPO_DIR#g" /etc/systemd/system/vera-mcp.service /etc/systemd/system/vera-web.service /etc/systemd/system/vera-demo-reset.service
fi
cp "$REPO_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl daemon-reload

echo "==> Restarting services"
systemctl restart vera-mcp vera-web
systemctl reload caddy

echo "==> Done. Check status with: sudo systemctl status vera-mcp vera-web caddy"
