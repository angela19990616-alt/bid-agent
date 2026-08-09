#!/usr/bin/env bash
set -euo pipefail

EXPECTED_DIR="${BID_AGENT_DIR:-/opt/bid-agent}"
DEPLOY_BRANCH="${BID_AGENT_BRANCH:-main}"
HEALTH_URL="${BID_AGENT_HEALTH_URL:-http://127.0.0.1:8080/health}"
BACKUP_DIR="${BID_AGENT_BACKUP_DIR:-$EXPECTED_DIR/backups}"

if [[ "$(pwd -P)" != "$EXPECTED_DIR" ]]; then
  echo "错误：必须在 $EXPECTED_DIR 执行部署。" >&2
  exit 2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "错误：服务器工作区存在未提交修改，已停止部署。" >&2
  exit 3
fi

previous_commit="$(git rev-parse HEAD)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$BACKUP_DIR/postgres-$timestamp.sql"

echo "部署前提交：$previous_commit"
echo "目标分支：$DEPLOY_BRANCH"

git fetch --prune origin
if git show-ref --verify --quiet "refs/heads/$DEPLOY_BRANCH"; then
  git switch "$DEPLOY_BRANCH"
else
  git switch --track -c "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
fi
git pull --ff-only origin "$DEPLOY_BRANCH"
target_commit="$(git rev-parse HEAD)"

mkdir -p "$BACKUP_DIR"
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' >"$backup_file"
test -s "$backup_file"
chmod 600 "$backup_file"
echo "数据库备份完成：$backup_file"

docker compose build backend worker frontend
docker compose up -d

healthy=0
for _ in $(seq 1 30); do
  if curl --fail --silent --show-error "$HEALTH_URL" >/dev/null \
    && curl --fail --silent --show-error \
      "http://127.0.0.1:8080/api/v1/access/status" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done

if [[ "$healthy" != "1" ]]; then
  echo "错误：部署后健康检查失败。" >&2
  docker compose ps >&2
  docker compose logs --tail=200 backend >&2
  docker compose logs --tail=200 worker >&2
  echo "代码回滚点：$previous_commit" >&2
  echo "数据库备份：$backup_file" >&2
  exit 4
fi

docker compose ps
echo "部署成功：$target_commit"
echo "代码回滚点：$previous_commit"
echo "数据库备份：$backup_file"
