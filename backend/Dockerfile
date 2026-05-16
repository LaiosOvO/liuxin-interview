# ============================================================
# Stage 1: builder — uv 安装依赖 + 编译 bytecode
# ============================================================
FROM ghcr.io/astral-sh/uv:0.10-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 先 copy pyproject.toml + uv.lock 利用 Docker 缓存层
COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 再 copy 源码 — 这一步源码变化不会重新装依赖
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ============================================================
# Stage 2: runtime — 只保留 venv + 源码
# ============================================================
FROM python:3.12-slim-bookworm AS runtime

# wget 用于 healthcheck；ca-certificates 用于 HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

WORKDIR /app

# 从 builder 拷 venv + 源码
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY migrations /app/migrations
COPY alembic.ini /app/
COPY entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "offboarding_flow.main:app", "--host", "0.0.0.0", "--port", "8000"]
