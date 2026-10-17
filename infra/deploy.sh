#!/usr/bin/env bash
# Deploy the current main branch to the EC2 instance.
#   EC2_HOST=ubuntu@<elastic-ip> DOMAIN=<domain> infra/deploy.sh
set -euo pipefail

: "${EC2_HOST:?set EC2_HOST, e.g. ubuntu@1.2.3.4}"
: "${DOMAIN:?set DOMAIN, e.g. mcpbridge.example.com}"
REPO_DIR="${REPO_DIR:-mcp-bridge}"
BRANCH="${BRANCH:-main}"

ssh "$EC2_HOST" bash -s <<EOF
set -euo pipefail
cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
docker compose --profile ec2 up -d --build
docker image prune -f >/dev/null
EOF

echo "Waiting for https://$DOMAIN/health ..."
for _ in $(seq 1 30); do
  if curl -fsS "https://$DOMAIN/health" >/dev/null; then
    echo "OK: https://$DOMAIN/health"
    exit 0
  fi
  sleep 2
done
echo "Health check failed" >&2
exit 1
