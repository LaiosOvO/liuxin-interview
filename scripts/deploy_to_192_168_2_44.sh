#!/bin/sh
# 离职流程系统 — 一键部署到 192.168.2.44 (DEPLOY-03)
#
# 适用场景：在 192.168.2.44 GigaByte laios 机器上拉最新代码 + 重启全套服务
# 前提：
#   - 本机已有 .env（POSTGRES_PASSWORD / SMTP_PASSWORD / JWT_SECRET 等真实凭证已填）
#   - 本机已有 docker + docker compose v2
#   - 当前用户能 docker compose（在 docker group 里）
#
# 默认行为：
#   1. git pull 最新 main
#   2. （可选）docker compose run frontend-build 构建前端产物（如果 frontend/out 不存在）
#   3. docker compose pull（基础镜像更新）
#   4. docker compose up -d --build（重建本地镜像并启）
#   5. 等 flow-api 健康
#   6. docker compose exec flow-api alembic upgrade head（确保 migration）
#   7. docker compose exec flow-api python -m offboarding_flow.flow_engine.checkpointer --setup
#   8. （可选）seed_demo_data.py（首次部署需要）
#   9. smoke test 探活
#
# 用法：
#   ./scripts/deploy_to_192_168_2_44.sh                  # 默认全套（含前端构建）
#   ./scripts/deploy_to_192_168_2_44.sh --no-frontend    # 跳过前端构建
#   ./scripts/deploy_to_192_168_2_44.sh --no-pull        # 跳过 git pull
#   ./scripts/deploy_to_192_168_2_44.sh --seed           # 显式跑 seed

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(dirname "$SCRIPT_DIR")
cd "$ROOT_DIR"

# ---- 参数解析 ----
SKIP_FRONTEND=0
SKIP_PULL=0
RUN_SEED=0
for arg in "$@"; do
  case "$arg" in
    --no-frontend) SKIP_FRONTEND=1 ;;
    --no-pull)     SKIP_PULL=1 ;;
    --seed)        RUN_SEED=1 ;;
    -h|--help)
      grep -E "^# " "$0" | head -30
      exit 0 ;;
    *) echo "[deploy] 未知参数: $arg" >&2; exit 2 ;;
  esac
done

echo "========================================================================"
echo "  [deploy] 离职流程系统 — 部署到 192.168.2.44"
echo "  当前路径: $ROOT_DIR"
echo "  当前分支: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
echo "  当前 commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "========================================================================"
echo ""

# 步骤 0: .env 校验
if [ ! -f .env ]; then
  echo "[deploy] ✗ .env 不存在 — 请先从 .env.example 复制并填真实凭证"
  exit 1
fi

# 步骤 1: git pull
if [ "$SKIP_PULL" -eq 0 ]; then
  echo "[deploy] >>> Step 1/8: git pull"
  git pull --ff-only origin "$(git rev-parse --abbrev-ref HEAD)" || {
    echo "[deploy] ✗ git pull 失败（非 fast-forward？需手工处理）"
    exit 1
  }
else
  echo "[deploy] - Step 1/8: 跳过 git pull (--no-pull)"
fi

# 步骤 2: 前端构建（如果 frontend/out 不存在 / 用户显式要构建）
if [ "$SKIP_FRONTEND" -eq 0 ]; then
  if [ ! -d frontend/out ] || [ "$1" = "--rebuild-frontend" ]; then
    echo "[deploy] >>> Step 2/8: 构建前端 (docker compose run frontend-build)"
    docker compose --profile build run --rm frontend-build || {
      echo "[deploy] ✗ 前端构建失败"
      exit 1
    }
  else
    echo "[deploy] - Step 2/8: frontend/out 已存在，跳过构建（如需重建用 --rebuild-frontend）"
  fi
else
  echo "[deploy] - Step 2/8: 跳过前端构建 (--no-frontend)"
fi

# 步骤 3: pull 基础镜像
echo "[deploy] >>> Step 3/8: docker compose pull"
docker compose pull || echo "[deploy] - pull 部分失败（可能是本地镜像 build 出来的，正常）"

# 步骤 4: up -d --build
echo "[deploy] >>> Step 4/8: docker compose up -d --build"
docker compose up -d --build

# 步骤 5: 等 flow-api 健康
echo "[deploy] >>> Step 5/8: 等 flow-api 健康..."
HEALTHY=0
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "[deploy] ✓ flow-api 健康 (after $((i*2))s)"
    HEALTHY=1
    break
  fi
  sleep 2
  printf "."
done
echo ""
if [ "$HEALTHY" -ne 1 ]; then
  echo "[deploy] ✗ flow-api 60s 未健康，日志:"
  docker compose logs --tail 100 flow-api
  exit 1
fi

# 步骤 6: alembic upgrade head（entrypoint.sh 已跑，再 explicit 一次防漏）
echo "[deploy] >>> Step 6/8: alembic upgrade head"
docker compose exec -T flow-api alembic upgrade head || {
  echo "[deploy] ✗ alembic 失败"
  exit 1
}

# 步骤 7: checkpointer.setup（同样 explicit）
echo "[deploy] >>> Step 7/8: checkpointer.setup()"
docker compose exec -T flow-api python -m offboarding_flow.flow_engine.checkpointer --setup || {
  echo "[deploy] ✗ checkpointer setup 失败"
  exit 1
}

# 步骤 8: seed（可选）
if [ "$RUN_SEED" -eq 1 ]; then
  echo "[deploy] >>> Step 8/8: 跑 seed_demo_data.py"
  docker compose exec -T flow-api python scripts/seed_demo_data.py || {
    echo "[deploy] ✗ seed 失败（可能 Mattermost 不可达？继续）"
  }
else
  echo "[deploy] - Step 8/8: 跳过 seed（如需 seed 加 --seed）"
fi

# 9: smoke test
echo ""
echo "[deploy] >>> 跑 smoke test 探活..."
if [ -x scripts/smoke_test.sh ]; then
  BASE_URL="http://localhost:8000" scripts/smoke_test.sh || {
    echo "[deploy] ✗ smoke test 失败 — 检查日志"
    exit 1
  }
fi

# 验证 nginx
echo ""
echo "[deploy] >>> nginx 探活..."
curl -sf http://localhost/nginx-health || {
  echo "[deploy] ✗ nginx 不健康"
  exit 1
}
echo "[deploy] ✓ nginx ok"

echo ""
echo "========================================================================"
echo "  [deploy] ✓ 部署完成"
echo "  访问入口:"
echo "    - 前端:        http://192.168.2.44/"
echo "    - API health:  http://192.168.2.44/api/health"
echo "    - Mattermost:  http://192.168.2.44:8065"
echo "    - MinIO:       http://192.168.2.44:9001"
echo "========================================================================"
