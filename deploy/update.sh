#!/usr/bin/env bash
# Puts the latest main branch on the server. Run it after merging a PR:
#   cd ~/prayerfit && deploy/update.sh
# It's also the first start. Migrations run by themselves when the backend starts.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

if [[ ! -f .env ]]; then
  echo "No .env here. Copy deploy/production.env.example to .env and fill it in." >&2
  exit 1
fi

echo "==> Getting the latest main"
# --ff-only: stop instead of making a merge if the server's copy was edited.
git pull --ff-only origin main

echo "==> Building and starting"
"${COMPOSE[@]}" up -d --build --remove-orphans

echo "==> Removing old images"
docker image prune -f

# Through Caddy, the same way a visitor gets there. The first start can
# take a minute while Caddy gets the certificate.
ORIGIN="$(grep -E '^APP_ORIGIN=' .env | cut -d= -f2-)"
echo "==> Checking $ORIGIN/api/health"
for _ in $(seq 1 30); do
  if curl -fsS "$ORIGIN/api/health"; then
    echo
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 5
done
echo "The site didn't answer. Look at the logs:  ${COMPOSE[*]} logs --tail 50" >&2
exit 1
