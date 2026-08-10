#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p media/{dramas,bgm,assets,clips,posts,packages,uploads} logs backend/data
if ! python3 scripts/doctor.py; then
  echo "❌ 环境体检未通过。请按上方每个‘怎么修’执行，然后重新运行 ./start.sh"
  exit 1
fi
docker compose up -d --build
HOST_IP=$(hostname -I | awk '{print $1}')
FRONTEND_BIND_PORT=${FRONTEND_BIND_PORT:-5174}
echo "✅ 服务已启动。打开 http://${HOST_IP:-127.0.0.1}:${FRONTEND_BIND_PORT} 开始使用"
