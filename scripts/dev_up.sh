#!/bin/sh
# 本地开发启动 — 起 postgres + redis + flow-api 三个容器
# 用 docker-compose.dev.yml override 启用 volume mount + --reload

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(dirname "$SCRIPT_DIR")

cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "[dev_up] .env 不存在，从 .env.example 复制（请编辑并设置真实凭证）"
  cp .env.example .env
  echo "[dev_up] >>> 请编辑 .env 设置 POSTGRES_PASSWORD 等真实值，再重跑本脚本"
  exit 1
fi

echo "[dev_up] 起容器（postgres + redis + flow-api）..."
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

echo "[dev_up] 等 flow-api 健康..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "[dev_up] ✓ flow-api 已健康"
    curl -s http://localhost:8000/api/health
    echo
    exit 0
  fi
  sleep 2
  printf "."
done

echo
echo "[dev_up] ✗ flow-api 60s 内未健康，检查日志:"
docker compose logs --tail 50 flow-api
exit 1
