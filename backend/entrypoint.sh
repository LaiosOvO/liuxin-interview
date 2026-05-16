#!/bin/sh
# offboarding-flow-api 启动脚本。
# 顺序（DEPLOY-05）：alembic upgrade head → checkpointer.setup() → uvicorn

set -e

echo "[entrypoint] === offboarding-flow-api starting ==="
echo "[entrypoint] APP_MODE=${APP_MODE:-demo}"
# 不打印密码部分（POSTGRES_DSN 一般是 postgresql+asyncpg://user:pass@host:port/db）
echo "[entrypoint] POSTGRES_DSN=${POSTGRES_DSN%@*}@***"

# Step 1: 业务表 migration（alembic 管理 app schema）
echo "[entrypoint] >>> alembic upgrade head"
alembic upgrade head

# Step 2: LangGraph checkpoint 表（由 AsyncPostgresSaver.setup() 自管 langgraph schema）
# CLI 入口在 backend/src/offboarding_flow/flow_engine/checkpointer.py
echo "[entrypoint] >>> python -m offboarding_flow.flow_engine.checkpointer --setup"
python -m offboarding_flow.flow_engine.checkpointer --setup

# Step 3: 启动 uvicorn（exec 替换 PID 1 让信号正确传递）
echo "[entrypoint] >>> exec $*"
exec "$@"
