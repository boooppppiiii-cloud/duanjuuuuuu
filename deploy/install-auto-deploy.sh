#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JUSHU_APP_DIR:-/home/ubuntu/social-ops-center}"
APP_USER="${JUSHU_APP_USER:-${SUDO_USER:-ubuntu}}"
STATE_DIR="/var/lib/jushu-auto-deploy"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Git repository not found: $APP_DIR" >&2
  exit 1
fi

APP_GROUP="$(id -gn "$APP_USER")"
install -d -m 0755 -o "$APP_USER" -g "$APP_GROUP" "$STATE_DIR"

cat >/usr/local/sbin/jushu-auto-deploy <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/social-ops-center"
STATE_DIR="/var/lib/jushu-auto-deploy"
MARKER="$STATE_DIR/last-successful-commit"

exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || exit 0

cd "$APP_DIR"
REMOTE_COMMIT="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
[[ -n "$REMOTE_COMMIT" ]] || { echo "Unable to resolve origin/main" >&2; exit 1; }

if [[ -f "$MARKER" ]] && [[ "$(cat "$MARKER")" == "$REMOTE_COMMIT" ]]; then
  exit 0
fi

echo "Deploying $REMOTE_COMMIT"
git fetch --prune origin main
git merge --ff-only origin/main
docker compose --profile production up -d --build

for attempt in $(seq 1 30); do
  if curl -fsS https://app.duanju.chat/api/health >/dev/null; then
    printf '%s\n' "$REMOTE_COMMIT" >"$MARKER"
    echo "Deployment healthy: $REMOTE_COMMIT"
    exit 0
  fi
  sleep 2
done

echo "Deployment completed but the public health check did not recover" >&2
exit 1
SCRIPT
chmod 0755 /usr/local/sbin/jushu-auto-deploy

cat >/etc/systemd/system/jushu-auto-deploy.service <<EOF
[Unit]
Description=Deploy Jushu from GitHub main
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
Environment=HOME=/home/$APP_USER
ExecStart=/usr/local/sbin/jushu-auto-deploy
TimeoutStartSec=3600
Nice=10
EOF

cat >/etc/systemd/system/jushu-auto-deploy.timer <<'EOF'
[Unit]
Description=Check for Jushu production updates every minute

[Timer]
OnBootSec=20s
OnUnitActiveSec=60s
RandomizedDelaySec=10s
Persistent=true
Unit=jushu-auto-deploy.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now jushu-auto-deploy.timer
systemctl start --no-block jushu-auto-deploy.service

echo "Jushu auto deployment is enabled."
echo "Status: systemctl status jushu-auto-deploy.timer"
echo "Logs:   journalctl -u jushu-auto-deploy.service -f"
