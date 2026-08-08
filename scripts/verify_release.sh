#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"

python_bin="${BID_AGENT_PYTHON:-$repo_root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo "错误：未找到 Python 环境：$python_bin" >&2
  exit 2
fi

echo "[1/7] Python 编译与未定义名称检查"
"$python_bin" -m compileall -q app scripts tests
"$python_bin" -m pyflakes app scripts tests

echo "[2/7] 规则配置与最短路径策略检查"
"$python_bin" scripts/verify_architecture.py

echo "[3/7] 后端全量测试"
"$python_bin" -m pytest

echo "[4/7] 前端生产构建"
npm --prefix frontend run build

echo "[5/7] Docker Compose 配置检查"
verify_env_created=0
if [[ ! -f .env ]]; then
  # Compose service-level env_file entries require the file to exist even
  # when all validation values are supplied by the CI environment. Keep the
  # real .env untracked; create only an empty, short-lived CI placeholder.
  : > .env
  verify_env_created=1
fi
cleanup_verify_env() {
  if [[ "$verify_env_created" == "1" ]]; then
    rm -f .env
  fi
}
trap cleanup_verify_env EXIT
if docker compose version >/dev/null 2>&1; then
  POSTGRES_PASSWORD=verify-only \
  BID_AGENT_EDGE_SECRET=verify-only \
  docker compose config --quiet
elif command -v docker-compose >/dev/null 2>&1; then
  POSTGRES_PASSWORD=verify-only \
  BID_AGENT_EDGE_SECRET=verify-only \
  docker-compose config --quiet
else
  echo "跳过：本机未安装 Docker Compose；CI/ECS 必须执行此项。"
fi
cleanup_verify_env
trap - EXIT

echo "[6/7] 已跟踪文件敏感信息检查"
if git grep -nI -E 'sk-[A-Za-z0-9_-]{24,}' -- \
  ':!*.example' ':!README.md'; then
  echo "错误：已跟踪文件疑似包含 API Key。" >&2
  exit 3
fi

echo "[7/7] Git 差异完整性检查"
git diff --check

echo "交付前检查通过。"
