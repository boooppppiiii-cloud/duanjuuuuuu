#!/usr/bin/env bash
set -euo pipefail

app_domain="${APP_DOMAIN:-app.duanju.chat}"
expected_ip="${EXPECTED_PUBLIC_IP:-43.159.41.222}"
dns_resolvers="${DNS_RESOLVERS:-1.1.1.1 8.8.8.8}"
max_attempts="${DNS_MAX_ATTEMPTS:-5760}"
poll_seconds="${DNS_POLL_SECONDS:-30}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

cd "$(dirname "$0")/.."

dns_is_ready() {
  local resolver
  while read -r resolver; do
    [[ -n "$resolver" ]] || continue
    if ! dig +short "@${resolver}" A "$app_domain" | grep -Fxq "$expected_ip"; then
      return 1
    fi
  done < <(tr ' ' '\n' <<< "$dns_resolvers")
  return 0
}

log "Waiting for ${app_domain} to be delegated publicly to ${expected_ip}"
for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  if dns_is_ready; then
      log "DNS is ready"
      docker compose --profile production config --quiet
      docker compose --profile production up -d --no-deps caddy
      docker compose --profile production exec -T caddy caddy reload --config /etc/caddy/Caddyfile

    for ((health_attempt = 1; health_attempt <= 30; health_attempt++)); do
      if curl --fail --silent --show-error --resolve "${app_domain}:443:127.0.0.1" "https://${app_domain}/api/health" >/dev/null; then
        log "HTTPS health check passed"
        docker compose --profile production ps
        exit 0
      fi
      sleep 10
    done

    log "Caddy started, but HTTPS health check did not pass within 5 minutes"
    docker compose --profile production logs --tail=120 caddy
    exit 1
  fi

  if ((attempt % 10 == 0)); then
    log "DNS is still propagating (attempt ${attempt}/${max_attempts})"
  fi
  sleep "$poll_seconds"
done

log "DNS did not become ready before the timeout; existing HTTP deployment was left unchanged"
exit 1
