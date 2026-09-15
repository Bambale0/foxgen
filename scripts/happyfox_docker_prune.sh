#!/usr/bin/env bash
set -Eeuo pipefail

LOCK_FILE="${HAPPYFOX_DOCKER_PRUNE_LOCK_FILE:-/run/lock/happyfox-docker-prune.lock}"
MAX_AGE="${HAPPYFOX_DOCKER_PRUNE_MAX_AGE:-120h}"

exec 9>"$LOCK_FILE"
flock -n 9 || {
  echo "happyfox_docker_prune outcome=skipped reason=already_running"
  exit 0
}

echo "happyfox_docker_prune stage=start max_age=$MAX_AGE"
df -h / | tail -n 1 | awk '{print "happyfox_docker_prune stage=disk_before used="$3" available="$4" use_percent="$5}'
docker system df || true

# Never prune Docker volumes here. HappyFox PostgreSQL, Redis and MinIO data
# live in named volumes and must survive routine Docker housekeeping.
docker container prune -f --filter "until=$MAX_AGE"
docker image prune -af --filter "until=$MAX_AGE"
docker builder prune -af --filter "until=$MAX_AGE"

df -h / | tail -n 1 | awk '{print "happyfox_docker_prune stage=disk_after used="$3" available="$4" use_percent="$5}'
docker system df || true
echo "happyfox_docker_prune stage=finish outcome=success max_age=$MAX_AGE"
