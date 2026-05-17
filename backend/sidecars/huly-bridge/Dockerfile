# ---------------------------------------------------------------------------
# huly-bridge sidecar — Node 22 alpine + tsx 运行时（无 tsc 编译步骤）
# Phase 8 / HULY-03
#
# 设计要点：
# - 与上游 huly v0.7.423 stack 同栈（Node 22-alpine）
# - tsx 直接跑 TS（节省 build 步骤，dev/prod 一致）
# - 端口 7777 暴露给 Python backend 调用
# - healthcheck 与 docker-compose.yml 段对齐
# ---------------------------------------------------------------------------
FROM node:22-alpine AS base
WORKDIR /app

# 仅 copy package.json 先利用 layer cache
COPY package.json package-lock.json* ./

# 安装依赖：优先 npm ci（依赖 package-lock.json）；首次构建无 lock 时退回 npm install
RUN npm ci --omit=dev || npm install --omit=dev

# 安装 tsx 运行时（生产也需要，因为我们不预编译）
RUN npm install --no-save tsx@4.19.0

# copy 源码 + 配置
COPY tsconfig.json ./
COPY src/ ./src/

# 暴露端口（与 docker-compose huly profile 一致）
EXPOSE 7777

# healthcheck 与 docker-compose healthcheck 同接口
HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=30s \
    CMD wget -qO- http://localhost:7777/healthz || exit 1

# 用 tsx 直接运行 TS
CMD ["npx", "tsx", "src/index.ts"]
