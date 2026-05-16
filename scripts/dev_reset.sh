#!/bin/sh
# 离职流程系统 — 开发数据库重置脚本（PITFALLS #9 — docker compose down -v 误删保护）
#
# 行为：
#   1. 二次确认（输入 RESET 或 yes 才继续）
#   2. 备份当前 postgres 数据到 /tmp/offboarding-pgdump-YYYYMMDD-HHMMSS.sql.gz
#   3. docker compose down -v（彻底清空业务表 + LangGraph checkpoint + Redis）
#   4. docker compose up -d（重启所有服务）
#   5. 等 flow-api 健康（最长 60s）
#   6. 提示用户跑 seed_demo_data.py
#
# 用法：
#   ./scripts/dev_reset.sh           # 交互确认
#   yes "yes" | ./scripts/dev_reset.sh   # CI 自动 yes（慎用）

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(dirname "$SCRIPT_DIR")
cd "$ROOT_DIR"

echo "========================================================================"
echo "  [dev_reset] 离职流程系统 — 重置开发环境"
echo "========================================================================"
echo ""
echo "  >>> 将执行的操作:"
echo "      1. 备份当前 postgres 数据到 /tmp/offboarding-pgdump-*.sql.gz"
echo "      2. docker compose down -v (彻底清空 postgres / redis / langgraph checkpoint)"
echo "      3. docker compose up -d (重启所有服务)"
echo ""
echo "  >>> 警告: 步骤 2 后所有业务数据 + 流程实例 + 演示账号将丢失"
echo ""

# 二次确认（PITFALLS #9）
printf "  请输入 RESET 或 yes 确认继续，其他任意输入退出: "
read -r CONFIRM
case "$CONFIRM" in
  RESET|reset|YES|yes|Y|y) ;;
  *)
    echo "  [dev_reset] 已取消"
    exit 0
    ;;
esac

# 步骤 1: 备份（容器在跑才备份；停了直接跳过）
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="/tmp/offboarding-pgdump-${TIMESTAMP}.sql.gz"
echo ""
echo "[dev_reset] >>> Step 1/5: 备份 postgres → ${BACKUP_FILE}"
if docker compose ps offboarding-postgres 2>/dev/null | grep -q "Up"; then
  if docker compose exec -T offboarding-postgres pg_dump -U flow -d offboarding 2>/dev/null \
      | gzip > "$BACKUP_FILE"; then
    BACKUP_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')
    echo "[dev_reset] ✓ 备份完成 (${BACKUP_SIZE})"
  else
    echo "[dev_reset] ✗ 备份失败 — 但仍继续重置（用户已确认 RESET）"
    rm -f "$BACKUP_FILE"
  fi
else
  echo "[dev_reset] - postgres 容器未在跑，跳过备份"
fi

# 步骤 2: down -v
echo ""
echo "[dev_reset] >>> Step 2/5: docker compose down -v (清空 volume)"
docker compose down -v

# 步骤 3: up -d
echo ""
echo "[dev_reset] >>> Step 3/5: docker compose up -d (重启所有服务)"
docker compose up -d

# 步骤 4: 等 flow-api 健康
echo ""
echo "[dev_reset] >>> Step 4/5: 等 flow-api 健康..."
HEALTHY=0
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "[dev_reset] ✓ flow-api 已健康 (after ${i}*2s)"
    HEALTHY=1
    break
  fi
  sleep 2
  printf "."
done
echo ""

if [ "$HEALTHY" -ne 1 ]; then
  echo "[dev_reset] ✗ flow-api 60s 内未健康，检查日志:"
  docker compose logs --tail 50 flow-api
  exit 1
fi

# 步骤 5: 提示 seed
echo ""
echo "[dev_reset] >>> Step 5/5: 下一步 — 执行 seed 脚本"
echo ""
echo "  docker compose exec flow-api python scripts/seed_demo_data.py"
echo ""
echo "  或本地直接跑:"
echo "  cd backend && uv run python ../scripts/seed_demo_data.py"
echo ""
echo "[dev_reset] ✓ 完成 — 备份: ${BACKUP_FILE}"
