#!/usr/bin/env bash
# Installs Vera on a fresh Ubuntu Lightsail instance: system packages,
# Python venv, systemd services (MCP server, web app, nightly demo
# reset), and Caddy as the HTTPS reverse proxy for vera.sha-i.com.
#
# Run from inside the cloned repo, as root (or with sudo):
#   cd /opt/vera && sudo bash deploy/setup.sh
#
# Safe to re-run -- it won't overwrite an existing /etc/vera/.env or
# Caddy's already-issued certificate. See deploy/DEPLOY.md for the full
# step-by-step, including what to do between the first and second run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER=vera
ENV_DIR=/etc/vera
ENV_FILE="$ENV_DIR/.env"

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root (sudo bash deploy/setup.sh)." >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null 2>&1; then
  echo "==> Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
else
  echo "==> Caddy already installed"
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  echo "==> Creating system user '$APP_USER'"
  useradd --system --home-dir "$REPO_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Setting up Python venv"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

echo "==> Preparing data directories"
mkdir -p "$REPO_DIR/data" "$REPO_DIR/web/cheer_media" "$REPO_DIR/web/audio_cache"
chown -R "$APP_USER:$APP_USER" "$REPO_DIR"

echo "==> Setting up secrets at $ENV_FILE"
mkdir -p "$ENV_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$REPO_DIR/.env.example" "$ENV_FILE"
  # VERA_DATA has a real default in .env.example already pointing at
  # /opt/vera/data/vera.json; if this checkout lives somewhere else,
  # match it.
  sed -i "s#^VERA_DATA=.*#VERA_DATA=$REPO_DIR/data/vera.json#" "$ENV_FILE"
  chown root:"$APP_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  NEEDS_EDIT=1
else
  echo "    $ENV_FILE already exists -- leaving it alone."
  NEEDS_EDIT=0
fi

echo "==> Installing systemd units"
cp "$REPO_DIR"/deploy/vera-mcp.service "$REPO_DIR"/deploy/vera-web.service \
   "$REPO_DIR"/deploy/vera-demo-reset.service "$REPO_DIR"/deploy/vera-demo-reset.timer \
   /etc/systemd/system/
# The unit files hardcode /opt/vera as WorkingDirectory/ExecStart -- patch
# them if this checkout lives somewhere else.
if [[ "$REPO_DIR" != "/opt/vera" ]]; then
  sed -i "s#/opt/vera#$REPO_DIR#g" /etc/systemd/system/vera-mcp.service /etc/systemd/system/vera-web.service /etc/systemd/system/vera-demo-reset.service
fi
systemctl daemon-reload
systemctl enable vera-mcp vera-web vera-demo-reset.timer

echo "==> Installing the Caddyfile (replaces /etc/caddy/Caddyfile)"
cp "$REPO_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl enable caddy

if [[ "$NEEDS_EDIT" -eq 1 ]]; then
  cat <<EOF

==> Almost done. Edit $ENV_FILE now and fill in:
      - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (the vera-deploy IAM user)
      - VERA_ACCESS_CODE   (the shared code your family will use)
      - VERA_MCP_TOKEN     (generate one with: openssl rand -hex 32)
      - VERA_S3_BUCKET, VERA_SES_FROM_EMAIL, etc. if you use them

    Then run this script again (or just):
      sudo systemctl start vera-mcp vera-web caddy
      sudo systemctl start vera-demo-reset.service   # seeds the demo profile now, instead of waiting for 3am
EOF
  exit 0
fi

echo "==> Starting services"
systemctl restart vera-mcp vera-web caddy
systemctl start vera-demo-reset.service

echo "==> Done. Check status with: sudo systemctl status vera-mcp vera-web caddy"
