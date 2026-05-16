# Stack Research — AI 驱动的离职流程执行系统

**Domain:** State-machine-driven HR offboarding workflow (LangGraph + FastAPI + Next.js)
**Researched:** 2026-05-16
**Overall Confidence:** HIGH（关键版本已通过 PyPI / npm / 官方 docs 在 2026-05 当下核对）

> 本 STACK.md 服务于 Phase 1（后端骨架 + LangGraph + Docker 编排）的 roadmap 创建。所有版本号截至 **2026-05-16** 验证；六个月后启动新 milestone 时需要重新核对。
>
> **锁定（用户已决策，不挑战）** vs **推荐（研究结论）** vs **可替换（次优但等价）** 三档明确标注。

---

## 0. 决策摘要（TL;DR）

| 维度 | 选型 | 版本 | 状态 |
|------|------|------|------|
| Python | CPython | 3.12.x | 锁定 |
| 包管理（后端）| uv | 0.5+ | 锁定 |
| Web 框架 | FastAPI | 0.136.1 | 锁定 |
| 数据校验 | Pydantic v2 + pydantic-settings | 2.x / 2.14.1 | 锁定 |
| ORM | SQLAlchemy 2.x async + asyncpg | 2.0.x / 0.30+ | 锁定 |
| 工作流引擎 | LangGraph | 1.2.0 | 锁定 |
| 工作流持久化 | langgraph-checkpoint-postgres (AsyncPostgresSaver) | 3.1.0 | 锁定 |
| DB 迁移 | Alembic（async 模板）| 1.18.x | 推荐 |
| JWT | PyJWT (`pyjwt[crypto]`) | 2.10+ | 推荐（替代 python-jose） |
| 邮件 | aiosmtplib + Jinja2 | 5.1.x / 3.1.x | 推荐 |
| HTTP 客户端 | httpx | 0.28+ | 推荐 |
| IM SDK | mattermostautodriver（同步）+ httpx（异步 webhook）| 11.6.1 | 推荐 |
| LLM SDK | OpenAI 兼容接口（`openai` 包指向智谱 base_url） | 1.x | 推荐 |
| 测试 | pytest + pytest-asyncio + httpx.AsyncClient + asgi-lifespan | — | 推荐 |
| Node | Node.js | 22 LTS | 推荐（pnpm 11 强制） |
| 包管理（前端）| pnpm | 11.1.1 | 锁定 |
| 前端框架 | Next.js（静态导出）| 15.x LTS | 锁定 |
| React | React | 19 stable | 跟随 Next.js |
| CSS | Tailwind CSS v4 | 4.x | 锁定 |
| 组件库 | shadcn/ui（CLI 0.9+） | 最新 | 锁定 |
| DB | PostgreSQL | 16-alpine | 锁定 |
| 缓存 | Redis | 7-alpine | 锁定 |
| 反代 | nginx | 1.27-alpine | 锁定 |
| 容器编排 | Docker Compose v2 | — | 锁定 |
| 后端镜像 | python:3.12-slim-bookworm（多阶段 + uv） | — | 推荐 |

---

## 1. Backend 核心栈

### 1.1 Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | **3.12.x**（最低 3.12，可走 3.13）| 运行时 | LangGraph / FastAPI / SQLAlchemy 2.x 都要求 ≥3.10；3.12 是 2026 主流 LTS-style 选择，性能更好且依赖完全兼容 |
| FastAPI | **0.136.1**（2026-04-23 发布）| ASGI Web 框架 | 项目已锁定。0.136.x 引入了严格 Content-Type 检查、SSE 原生支持、Starlette 升级到 0.46+；建议在 `pyproject.toml` 用 `fastapi>=0.136,<0.140` 留升级空间。**安装时用 `fastapi[standard]`**（自带 uvicorn、httpx、email-validator） |
| uvicorn | 随 `fastapi[standard]` 进来 | ASGI 服务器 | 内网部署不需要 gunicorn 进程管理（容器即进程）；用 `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2` |
| Pydantic | **2.x**（具体跟 fastapi 走，预计 2.10+） | 数据校验 | FastAPI 0.136 强依赖 Pydantic v2；v1 已不支持 |
| pydantic-settings | **2.14.1**（2026-05-08） | 环境变量配置 | 替代旧 BaseSettings；与 `.env` 文件原生集成，校验失败即 fail-fast |
| SQLAlchemy | **2.0.x（最新 2.0.43+，避免 3.x alpha）** | ORM | 项目锁定 2.x async；用 `select()` / `session.execute()` 新 API，不要写 1.x 风格的 `query()` |
| asyncpg | **0.30+**（注意：2.0.x SQLAlchemy 老版本要求 asyncpg<0.29，但近半年的 SQLAlchemy 2.0.30+ 已放开此约束）| Postgres async 驱动 | 比 psycopg 异步模式快约 2-3 倍；DSN 必须用 `postgresql+asyncpg://`（用 `postgresql://` 会同步阻塞 event loop） |
| greenlet | 随 SQLAlchemy async 进来 | SQLAlchemy 异步桥 | 不需要显式安装，但 Docker base image 必须能编译 C 扩展（slim 可，alpine 会卡） |
| LangGraph | **1.2.0**（2026-05-12 发布） | 状态机/工作流引擎 | 1.x 是 production-ready GA 版本；1.2 新增 per-node 超时、DeltaChannel、graceful drain。v1 项目用 1.2.x 但 pin `langgraph>=1.2,<1.3` 避免不期望的次版本破坏 |
| langgraph-checkpoint-postgres | **3.1.0**（2026-05-12） | LangGraph 持久化层 | **关键包名易混淆**：PyPI 包名是 `langgraph-checkpoint-postgres`，Python 导入路径是 `from langgraph.checkpoint.postgres import PostgresSaver` / `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`。底层用 psycopg 3（不是 asyncpg），所以业务用 asyncpg + checkpoint 用 psycopg = 同一 Postgres 实例两个连接池并存（按 PRD §5.3 是 OK 的）|
| psycopg[binary] | **3.2+** | LangGraph checkpoint 用 | 因为 langgraph-checkpoint-postgres 底层用 psycopg 3，必须装；用 `psycopg[binary]` 避免本地编译 |

### 1.2 Supporting Libraries（Backend）

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **alembic** | **1.18.x**（2026 最新）| DB 迁移 | 业务表（不是 LangGraph checkpoint 表）。用 `alembic init -t async` 生成 async 模板，env.py 必须用 `async_engine_from_config`，`NullPool`，`connection.run_sync(do_run_migrations)`。LangGraph checkpoint 表由 `await saver.setup()` 自管，**不要纳入 alembic** |
| **aiosmtplib** | **5.1.x** | 异步 SMTP | QQ 邮箱必须 `port=465 + use_tls=True`（注意：是 implicit TLS，不是 STARTTLS；start_tls=False）；`username=1624456575@qq.com`、`password=授权码（16 位）` |
| **jinja2** | **3.1.x** | 邮件 HTML 模板 | 渲染节点通知邮件 + 申请人最终确认时间线邮件；`autoescape=select_autoescape(["html"])` 防 XSS |
| **httpx** | **0.28+** | HTTP 客户端 | Mattermost REST API、智谱 GLM API、测试 AsyncClient 都用它；统一一个 client 避免连接池碎片 |
| **pyjwt[crypto]** | **2.10+** | JWT 签发/校验 | 用 HS256（v1 简单签发），无需 RS256；`encode({...}, JWT_SECRET, algorithm="HS256")`。**不要用 python-jose**（2021 年后基本未维护，已被 FastAPI 官方移除推荐） |
| **redis[hiredis]** | **5.x async** | jti 黑名单 + 超时队列 | 用 `redis.asyncio` 子包（同一个包，新 API）；hiredis 加速解析 |
| **zhipuai 或 openai** | openai 1.x | GLM 调用 | **推荐用官方 `openai` 包**，配置 `base_url="https://open.bigmodel.cn/api/paas/v4/"` 走 OpenAI 兼容接口；好处：未来切模型零代码改动，调用模式标准。`zhipuai` SDK 也可用（最新 v4 系列），但绑死单一 provider |
| **mattermostautodriver** | **11.6.1**（2026-04-21） | Mattermost API 客户端 | OpenAPI 自动生成，跟随 Mattermost server 版本；但**只支持同步**。**推荐组合**：seed 脚本（一次性 CLI）用 mattermostautodriver；运行时 IM 推送（在 async 节点函数里）直接用 httpx 调 incoming webhook / `/api/v4/posts` REST，避免 sync/async 桥接成本 |
| **structlog** | 24.x | 结构化日志 | JSON 日志便于 Loki/Grafana 聚合；优于 logging 的字符串拼接 |
| **tenacity** | 9.x | 重试 | 通知发送、LLM 调用的指数退避重试（FLOW-04、LLM-03） |

### 1.3 Backend 测试栈

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| pytest | 8.x | 测试框架 | — |
| pytest-asyncio | **0.24+** | async 测试 | `asyncio_mode = "auto"` 在 `pyproject.toml [tool.pytest.ini_options]` 里设，写测试不用每个加 `@pytest.mark.asyncio` |
| httpx.AsyncClient | 同 httpx 0.28 | API 集成测试 | 配合 `asgi-lifespan` 触发 FastAPI lifespan 事件 |
| **asgi-lifespan** | 2.x | 测试时触发 lifespan | FastAPI 官方文档推荐组合（async tests 章节）|
| pytest-cov | 5.x | 覆盖率 | 用户全局规则要求 ≥80% |
| pytest-mock | 3.x | mock | 替代 unittest.mock，更符合 pytest 风格 |
| polyfactory | 2.x | 测试数据工厂 | **替代 factory-boy**：factory-boy 不原生支持 Pydantic v2 / SQLAlchemy 2.x async；polyfactory 是 Pydantic-first 现代方案 |
| respx | 0.21+ | mock httpx 调用 | mock GLM/Mattermost HTTP 调用，比 mock 客户端方法更稳 |

### 1.4 Backend 安装（uv 命令）

```bash
# 在 backend/ 目录初始化
uv init --package . --python 3.12

# 核心运行时依赖
uv add 'fastapi[standard]>=0.136,<0.140'
uv add 'pydantic-settings>=2.14'
uv add 'sqlalchemy[asyncio]>=2.0.30,<2.1'
uv add 'asyncpg>=0.30'
uv add 'alembic>=1.18'
uv add 'langgraph>=1.2,<1.3'
uv add 'langgraph-checkpoint-postgres>=3.1,<4'
uv add 'psycopg[binary]>=3.2'
uv add 'aiosmtplib>=5.1'
uv add 'jinja2>=3.1'
uv add 'httpx>=0.28'
uv add 'pyjwt[crypto]>=2.10'
uv add 'redis[hiredis]>=5.0'
uv add 'openai>=1.40'                  # 走智谱 OpenAI 兼容 base_url
uv add 'mattermostautodriver>=11.6'    # 仅 seed 脚本使用
uv add 'structlog>=24'
uv add 'tenacity>=9'

# 开发组
uv add --dev pytest pytest-asyncio pytest-cov pytest-mock asgi-lifespan polyfactory respx
uv add --dev ruff mypy

# 运行
uv run uvicorn app.main:app --reload --port 8000
uv run alembic upgrade head
uv run pytest --cov=app --cov-report=term-missing
```

---

## 2. Frontend 栈

### 2.1 Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Node.js | **22 LTS**（不是 20）| 运行时 | **关键变化**：pnpm 11 强制要求 Node 22+；Next.js 15 完全兼容 Node 22；Docker image 用 `node:22-alpine` 仅做构建，不进生产容器 |
| pnpm | **11.1.1**（2026-05-12）| 包管理 | 锁定。corepack enable 后用 `corepack prepare pnpm@11.1.1 --activate` 固定版本，写入 `package.json` 的 `packageManager` 字段 |
| Next.js | **15 LTS（15.5.x 最新补丁）** | 前端框架 | 用户锁定 15。Next.js 15 是 LTS 到 2026-10-21；16 已发但与用户决策不符。`output: 'export'` 在 15.x 完全支持，配 React 19 stable |
| React | **19.x stable** | UI 库 | Next.js 15.1+ 默认 React 19；shadcn/ui 已全面兼容 |
| TypeScript | **5.6+** | 类型 | Next.js 15.5 内置升级 |
| Tailwind CSS | **v4.x** | CSS | 锁定。**v4 与 v3 配置方式完全不同**：CSS-first（在 globals.css 里 `@import "tailwindcss"`），不再用 tailwind.config.js；PostCSS 配置用 `@tailwindcss/postcss` |
| shadcn/ui | **CLI 最新**（不是版本号，是源码复制工具）| 组件库 | `pnpm dlx shadcn@latest init` 会检测 Tailwind v4 并自动用 v4 配置（CSS 变量注入到 `@theme` directive） |

### 2.2 Frontend Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| swr 或 @tanstack/react-query | 2.x / 5.x | 客户端数据获取 | 静态导出模式下所有动态数据必须客户端拉取；**推荐 SWR**（更轻量，shadcn/ui 示例常用） |
| react-hook-form + zod | 7.x / 3.x | 表单 | 三态决策表单（result_text 必填，reason 条件必填）|
| lucide-react | 最新 | 图标 | shadcn/ui 默认图标库，无需替换 |
| date-fns | 4.x | 日期 | 时间线渲染、超时倒计时；**不要用 moment.js**（已 deprecated）|

### 2.3 Next.js 15 + `output: 'export'` 动态路由的关键限制（HIGH 风险）

PRD §10.0.1 说"动态路由（如 `/flow/[flow_id]/node/[node_id]`）走客户端渲染：构建期生成壳页面 + `useParams()` + `fetch()` 拉数据" —— **这个方案在 Next.js 15 App Router + `output: 'export'` 下不能直接工作**。

**问题**：App Router 的 dynamic segment 在 export 模式下要求 `generateStaticParams()` 返回所有路径在构建期预渲染；运行时 `useParams()` 在静态导出中不会自动拿到动态值。这是 [vercel/next.js#79380](https://github.com/vercel/next.js/issues/79380) 长期 issue。

**两个可行方案**（推荐方案 A）：

#### 方案 A（推荐）：用 query string 代替 path param

把深链从 `/flow/[flow_id]/node/[node_id]?token=xxx` 改为 `/flow/handle?flow_id=xxx&node_id=yyy&token=zzz`。这样只有一个静态壳页面 `/flow/handle/index.html`，所有动态参数走 query string，`useSearchParams()` 在 export 模式下完全工作。

```typescript
// app/flow/handle/page.tsx
"use client";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

export default function Page() {
  const params = useSearchParams();
  const flowId = params.get("flow_id");
  const nodeId = params.get("node_id");
  const token = params.get("token");
  // 进入页面立刻 exchange token → cookie，然后用 cookie 拉 view
  const { data } = useSWR(
    flowId && nodeId ? `/api/flows/${flowId}/nodes/${nodeId}/view` : null,
    fetcher
  );
  // ...
}
```

**唯一影响**：邮件深链的 URL 不再像 RESTful path，但语义不变，token 安全性零影响。**强烈建议在 v1 用这个方案**。

#### 方案 B（如果坚持 path param）：generateStaticParams 返回空 + nginx fallback

```typescript
// app/flow/[flow_id]/node/[node_id]/page.tsx
export const dynamic = "force-static";
export const dynamicParams = true; // 允许未在 generateStaticParams 里的路径
export async function generateStaticParams() { return []; }
```

然后 nginx 的 `try_files` 兜底回 `/index.html`，让 React Router 接管。**但这种组合在 Next.js 15 App Router 下行为不稳定**（社区报告 `useParams()` 返回 undefined 的 race condition），不推荐 v1 用。

> **决策建议**：roadmap Phase 4（前端）把深链格式统一改为 `/flow/handle?flow_id=...&node_id=...&token=...`。后端的 `build_deep_link` 函数同步调整。

### 2.4 Tailwind CSS v4 安装（与 v3 截然不同，必看）

```bash
# 创建 Next.js 15 项目（pnpm + TS + Tailwind v4）
pnpm create next-app@15 frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*"
# create-next-app@15 自动用 Tailwind v4

# 安装 shadcn/ui（CLI 检测 Tailwind v4 并适配）
cd frontend
pnpm dlx shadcn@latest init
# 选择 base color: zinc / 选择 New York style（更现代）

# 添加组件（按需）
pnpm dlx shadcn@latest add button form input textarea radio-group toast card table
```

**关键配置文件示例**：

```css
/* app/globals.css — Tailwind v4 入口（替代 v3 的三条 @tailwind 指令）*/
@import "tailwindcss";

@theme {
  --color-primary: oklch(0.65 0.18 250);
  /* shadcn/ui init 会在这里注入 --background / --foreground / --primary 等 CSS 变量 */
}
```

```javascript
// postcss.config.mjs — v4 用 @tailwindcss/postcss
const config = {
  plugins: { "@tailwindcss/postcss": {} },
};
export default config;
```

```javascript
// next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,      // 让 nginx 的 try_files 行为更可预测
  images: { unoptimized: true },  // 静态导出必须关掉 Image Optimization
};
export default nextConfig;
```

### 2.5 Frontend 安装（pnpm 命令）

```bash
cd frontend
pnpm install
pnpm add swr react-hook-form zod @hookform/resolvers date-fns
pnpm add -D @types/node

# shadcn 组件按需添加
pnpm dlx shadcn@latest add button input textarea radio-group form card table toast separator badge

# 构建
pnpm build   # 产出 out/
```

---

## 3. Infrastructure 栈

### 3.1 Core Infrastructure

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| PostgreSQL | **16-alpine** | 业务表 + LangGraph checkpoint | 用同一实例两个 schema（如 `app` 和 `langgraph`）；Postgres 17 已 GA 但 16 是更稳定的 LTS-style 选择；alpine 镜像约 230MB 比 standard 小 |
| Redis | **7-alpine** | jti 黑名单 + 超时扫描队列 | 7.x 稳定多年；alpine 镜像约 30MB |
| nginx | **1.27-alpine** | 反代 + 静态 serve | 1.27 stable 系列；1.29 mainline 也可但不需要 |
| Docker Compose | **v2**（Docker 25+ 自带） | 编排 | 不要再用 docker-compose v1（python 版）；用 `docker compose` 命令而非 `docker-compose` |

### 3.2 后端 Docker 镜像选型

**推荐：`python:3.12-slim-bookworm` + uv 多阶段构建**

| 选项 | 镜像大小 | 构建速度 | 维护成本 | 决策 |
|------|---------|---------|---------|------|
| python:3.12-slim-bookworm | ~150MB（runtime） | 快 | 低（apt 生态完整）| ✅ 推荐 |
| python:3.12-alpine | ~50MB | **慢 5-10x**（asyncpg / psycopg / cryptography 全部要从源码编译，因为 musl libc 不兼容 manylinux wheel）| 高（musl 兼容陷阱）| ❌ 不推荐 |
| ghcr.io/astral-sh/uv:python3.12-bookworm-slim | ~120MB | 最快（uv 内置）| 低 | ✅ 可替换（更现代） |
| python:3.12（full）| ~1GB | 快 | 低 | ❌ 体积过大 |
| distroless | ~80MB | 复杂 | 高（debug 困难） | ❌ 演示项目不值得 |

**最小 Dockerfile（uv 多阶段）**：

```dockerfile
# backend/Dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
# 先装依赖（层缓存友好）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
# 再装项目
COPY app ./app
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
WORKDIR /app
# 把 venv 整个搬过来（不需要 uv 在运行时）
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3.3 nginx 配置（PRD §10.0.2 增强版）

PRD 已给出基础配置，研究阶段增强建议：

```nginx
# nginx/conf.d/default.conf
upstream flow_api {
    server flow-api:8000;
    keepalive 32;   # 持久连接，减少握手
}

server {
    listen 80;
    server_name 192.168.2.44 _;
    
    # 安全 / 性能基础
    client_max_body_size 10M;          # 防超大请求
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    # 1. API 反代
    location /api/ {
        proxy_pass http://flow_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";  # 启用 upstream keepalive
        proxy_read_timeout 90s;
        proxy_send_timeout 90s;
    }

    # 2. WebSocket（如 v1.1 需要实时推送状态）
    location /ws/ {
        proxy_pass http://flow_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;       # WebSocket 长连接
    }

    # 3. 静态前端（Next.js export 产物）
    location / {
        root /usr/share/nginx/html;
        # try_files 顺序：精确文件 → 加 .html → 加 /index.html → 兜底根 index.html
        try_files $uri $uri.html $uri/index.html /index.html;
        
        # 静态资源缓存（Next.js 产物文件名带 hash，可安全长缓存）
        location /_next/static/ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }

    # 4. healthcheck（容器编排用）
    location = /nginx-health {
        access_log off;
        return 200 "ok\n";
    }
}
```

### 3.4 docker-compose.yml 骨架

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: flow
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: flow_db
    volumes: ["pg_data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U flow -d flow_db"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes: ["redis_data:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10
    restart: unless-stopped

  flow-api:
    build: ./backend
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 10s
      retries: 5
    restart: unless-stopped

  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80"]
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./frontend/out:/usr/share/nginx/html:ro   # 前端构建产物挂载
    depends_on:
      flow-api: { condition: service_healthy }
    restart: unless-stopped

volumes:
  pg_data:
  redis_data:
```

---

## 4. 关键最小可运行配置示例

### 4.1 LangGraph + AsyncPostgresSaver（FLOW-01/03 基础）

```python
# app/flow/engine.py
from contextlib import asynccontextmanager
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

class OffboardingState(TypedDict, total=False):
    employee_id: str
    flow_id: str
    decisions: dict
    current_action: str

def build_graph(checkpointer):
    g = StateGraph(OffboardingState)
    g.add_node("apply", apply_node)
    g.add_node("manager_review", manager_review_node)
    g.add_node("hr_initial", hr_initial_node)
    # ... 10 个节点
    g.add_edge(START, "apply")
    g.add_edge("apply", "manager_review")
    g.add_conditional_edges("manager_review", route_after_manager,
                            {"advance": "hr_initial", "reject": END})
    return g.compile(checkpointer=checkpointer)

# 业务节点用 interrupt() 而非旧版的 interrupt_before
async def manager_review_node(state: OffboardingState):
    # 1. 写业务表 + 发通知（PRD §5.3.1 双写）
    await state_store.upsert_node_state(...)
    await notification_dispatcher.dispatch(...)
    # 2. 挂起等待人工
    decision = interrupt({"prompt": "请上级审批", "node": "manager_review"})
    # 3. 收到 Command(resume={...}) 后继续
    return {"decisions": {**state.get("decisions", {}), "manager_review": decision},
            "current_action": decision["action"]}

# FastAPI lifespan 中初始化 checkpointer + graph
@asynccontextmanager
async def lifespan(app):
    # 关键：autocommit=True + row_factory=dict_row（官方要求）
    pool = AsyncConnectionPool(
        conninfo=settings.LANGGRAPH_DSN,    # postgresql://flow:...@postgres:5432/flow_db
        max_size=10,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()              # 首次运行创建表
    app.state.graph = build_graph(checkpointer)
    app.state.checkpointer = checkpointer
    yield
    await pool.close()

# API 路由：人工动作回调 → Command(resume=...)
async def submit_action(flow_id: str, node_id: str, payload: ActionRequest):
    config = {"configurable": {"thread_id": flow_id}}
    await state_store.write_action_log(...)
    await app.state.graph.ainvoke(
        Command(resume={"action": payload.action,
                        "result_text": payload.result_text,
                        "reason": payload.reason}),
        config=config,
    )
```

**关键 API 变化（2026 vs 旧资料）**：
- ✅ 用 `interrupt()` 函数 + `Command(resume=...)`（LangGraph 1.x 推荐）
- ❌ 不用旧的 `interrupt_before=[...]` 在 compile 时声明（仍支持但不灵活）
- ✅ 用 `AsyncPostgresSaver(pool)`（手动 pool）或 `AsyncPostgresSaver.from_conn_string(dsn)`（context manager）
- ✅ 用 `ainvoke` / `astream`，不要在 async FastAPI 里调同步 `invoke`

### 4.2 SQLAlchemy 2.x async + asyncpg + FastAPI Depends

```python
# app/db.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool

engine = create_async_engine(
    settings.POSTGRES_DSN,                  # postgresql+asyncpg://flow:...@postgres:5432/flow_db
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 4.3 Alembic async env.py（关键片段）

```python
# alembic/env.py（基于 alembic init -t async 模板）
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

# 必须导入所有模型让 Base.metadata 完整
from app.models import Base
target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.POSTGRES_DSN)

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

asyncio.run(run_migrations_online())
```

### 4.4 JWT 一键登录（pyjwt）

```python
# app/auth/jwt.py
import jwt, uuid
from datetime import datetime, timedelta, timezone

def sign_deeplink_token(*, sub: str, role: str, flow_id: str, node_id: str,
                        node_name: str, allowed_actions: list[str]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub, "role": role,
        "flow_id": flow_id, "node_id": node_id, "node_name": node_name,
        "allowed_actions": allowed_actions,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.TOKEN_EXPIRY_HOURS)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid token")
```

### 4.5 aiosmtplib + Jinja2（QQ 邮箱 SSL）

```python
# app/notification/email.py
import aiosmtplib
from email.message import EmailMessage
from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(
    loader=FileSystemLoader("app/templates/email"),
    autoescape=select_autoescape(["html"]),
)

async def send_email(*, to: str, subject: str, template: str, ctx: dict):
    html = env.get_template(template).render(**ctx)
    msg = EmailMessage()
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("您的邮件客户端不支持 HTML，请用现代客户端查看")
    msg.add_alternative(html, subtype="html")
    
    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,        # smtp.qq.com
        port=settings.SMTP_PORT,            # 465
        use_tls=True,                       # implicit TLS（QQ 强制）
        start_tls=False,                    # 不是 STARTTLS
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,    # 授权码
        timeout=30,
    )
```

### 4.6 GLM via OpenAI-compatible（LLM-01/02）

```python
# app/llm/glm.py
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

client = AsyncOpenAI(
    api_key=settings.GLM_API_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def summarize_node_results(node_results: list[dict]) -> str | None:
    """申请人最终确认邮件的摘要段。失败返回 None，由调用方降级（LLM-03）。"""
    try:
        resp = await client.chat.completions.create(
            model="glm-4.6",
            messages=[
                {"role": "system", "content": "你是 HR 助手，把离职流程的各节点结果做 3 句话中文总结。"},
                {"role": "user", "content": str(node_results)},
            ],
            timeout=15,
            max_tokens=300,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning("glm_summarize_failed", error=str(e))
        return None
```

---

## 5. Alternatives Considered（次优但记录决策）

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| FastAPI | Litestar / Starlette 裸用 | Litestar DI 更高级但社区比 FastAPI 小一个数量级；本项目体积下不值得换 |
| LangGraph | Temporal / Camunda 8 | 真正企业级长事务（数周-数月）场景；本项目流程 ≤7 天，LangGraph 足够 |
| asyncpg | psycopg 3 async | 与 LangGraph checkpoint 统一驱动；但 asyncpg 性能更好，分两个驱动 OK |
| pyjwt | authlib | 需要完整 OAuth2 server / 多 provider OIDC 时；v1 不需要 |
| mattermostautodriver（同步）+ httpx（异步）| python-mattermost-driver | 后者更新已停滞（最新 7.3.1 是 2023 年）|
| openai 包指向智谱 | zhipuai 官方 SDK | 锁定智谱 + 用智谱专有能力（如 GLM 函数调用扩展）时 |
| Tailwind v4 | Tailwind v3 | v3 配置更熟悉但已不是默认；shadcn/ui 新项目默认 v4 |
| polyfactory | factory-boy | factory-boy 不原生支持 Pydantic v2 + SQLAlchemy 2 async |
| Next.js 15 静态导出 | Next.js 15 SSR + Node 容器 | 需要 RSC / API routes / middleware 时；本项目所有动态走 FastAPI，不需要 |

---

## 6. What NOT to Use（明确禁用）

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Poetry** | 用户全局规则强制 uv；uv 速度快 10-100x | uv |
| **pip-tools** | 同上 | uv |
| **SQLAlchemy 1.x sync** | 锁定 2.x async；1.x query API 已 legacy | SQLAlchemy 2.x + asyncpg |
| **Flask** | 锁定 FastAPI；Flask 没原生 async/校验 | FastAPI |
| **python-jose** | 2021 年起基本未维护；有 CVE 历史；FastAPI 官方已移除推荐 | pyjwt[crypto] |
| **factory-boy** | 不原生支持 Pydantic v2 / SQLAlchemy 2 async | polyfactory |
| **moment.js** | 已被作者标记 legacy；体积大 | date-fns |
| **webpack / CRA** | 锁定 Next.js | Next.js 15 |
| **alpine 镜像跑 Python** | musl libc 不兼容 manylinux wheel，asyncpg/cryptography 全部本地编译，构建慢 5-10 倍 | python:3.12-slim-bookworm |
| **psycopg2** | 同步 + 老旧 | psycopg 3（LangGraph 用）+ asyncpg（业务用） |
| **Tailwind v3 + tailwind.config.js** | shadcn/ui 新项目默认 v4，v3 安装时 init 流程不同需手动配置 | Tailwind v4 + `@import "tailwindcss"` |
| **Next.js App Router 动态路径 + output: 'export'** | 见 §2.3，运行时 useParams 不稳定 | query string 方案（推荐方案 A） |
| **pnpm 10.x 或更早** | pnpm 11 强制 Node 22+，新项目从 11 开始一致性最好 | pnpm 11.1.1 + Node 22 LTS |
| **docker-compose v1（python）** | EOL；命令是 `docker-compose` 不是 `docker compose` | Docker Compose v2（随 Docker 25+） |
| **interrupt_before（旧 LangGraph API）** | 1.x 推荐 interrupt() 函数 + Command(resume=)，更灵活 | `from langgraph.types import interrupt, Command` |
| **`postgresql://` DSN（非 +asyncpg）** | SQLAlchemy 会回退到同步驱动并阻塞 event loop，不会报错 | `postgresql+asyncpg://...`（业务）+ `postgresql://...`（LangGraph checkpoint 用 psycopg） |

---

## 7. Version Compatibility Matrix（关键兼容关系）

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| langgraph 1.2.x | langgraph-checkpoint-postgres 3.1.x | 1.x 系列内 minor 兼容；checkpoint 3.x 是 1.x 配套 |
| langgraph-checkpoint-postgres 3.1.x | psycopg[binary] >=3.2 | **不用** asyncpg；用 psycopg 3 |
| SQLAlchemy 2.0.30+ | asyncpg 0.30+ | 老版本 SQLAlchemy 要求 asyncpg<0.29，新版已放开 |
| FastAPI 0.136.x | Pydantic 2.x, Starlette >=0.46 | Pydantic v1 已不支持 |
| Next.js 15.5 | React 19 stable, Node 22+ | React 18 仍支持但默认 19 |
| pnpm 11.x | Node 22+ | Node 20 已被 drop |
| Tailwind v4 | PostCSS via `@tailwindcss/postcss` | 不再用 tailwind.config.js，CSS-first |
| shadcn/ui CLI 最新 | Tailwind v3 和 v4 都支持 | 自动检测项目版本 |
| aiosmtplib 5.x | Python 3.10+ | 5.x 是 2025 重写版本，async API 更稳 |
| pytest-asyncio 0.24 | pytest 8+ | `asyncio_mode="auto"` 推荐 |

---

## 8. Stack Patterns by Variant

**如果未来需要 LangGraph 集群部署（多个 flow-api 实例）：**
- 用 LangGraph Platform（商业）或自管 Redis 加 LangGraph 内置的分布式锁
- v1 单实例足够，按 PRD 不考虑

**如果未来切到生产真实邮箱：**
- aiosmtplib 配置不变，只需把 SMTP_HOST / SMTP_USER / APP_MODE 切换
- 业务代码零修改（PRD §7.4.4 已设计好开关）

**如果未来需要 SSO 替代 JWT 深链：**
- pyjwt 仍保留（用于内部 service-to-service token）
- 加 authlib 做 OAuth2 client 对接 Mattermost OAuth2 / 企业 OIDC
- 现在的 deeplink 路由保留作为 fallback

**如果未来加多语言：**
- Next.js 15 用 next-intl（不要用旧的 next-i18next）
- 后端邮件模板分目录 `templates/email/zh/`、`templates/email/en/`

---

## 9. Confidence Levels

| Recommendation | Confidence | Source |
|----------------|------------|--------|
| LangGraph 1.2.0 + checkpoint-postgres 3.1.0 | **HIGH** | PyPI 直接验证（2026-05-12 发布） |
| FastAPI 0.136.1 | **HIGH** | PyPI 直接验证（2026-04-23 发布） |
| pnpm 11.1.1 + Node 22 要求 | **HIGH** | pnpm 官方 blog + release notes |
| Next.js 15 LTS 到 2026-10 | **HIGH** | endoflife.date 验证 |
| Tailwind v4 + shadcn/ui 集成方式 | **HIGH** | shadcn/ui 官方 docs |
| `output: 'export'` + 动态路由限制 | **HIGH** | Next.js 长期 issue #79380 + GitHub discussions |
| openai 包 + 智谱 base_url 兼容 | **MEDIUM** | 智谱官方文档说明 OpenAI 兼容，但 v1 项目应做小 POC 验证 |
| mattermostautodriver vs httpx 直调选择 | **MEDIUM** | 综合社区共识 + 同步/异步桥接成本判断 |
| python-jose 不推荐 | **HIGH** | FastAPI 官方 discussion #11345 明确移除推荐 |
| polyfactory 替代 factory-boy | **MEDIUM** | 社区共识，但 v1 测试简单可能直接手写 fixture |
| AsyncPostgresSaver pool 模式（autocommit + dict_row）| **HIGH** | langgraph-checkpoint-postgres 官方 docs 明文要求 |

---

## 10. Sources（核心来源 + 验证级别）

### Authoritative (HIGH confidence)
- [langgraph 1.2.0 on PyPI](https://pypi.org/project/langgraph/) — 版本号 + 发布日期直接验证
- [langgraph-checkpoint-postgres 3.1.0 on PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/) — 同上，含初始化要求
- [LangGraph Interrupts docs (LangChain)](https://docs.langchain.com/oss/python/langgraph/interrupts) — interrupt() + Command(resume=) 2026 API
- [PostgresSaver source](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py) — 导入路径 + from_conn_string 签名
- [FastAPI 0.136.1 on PyPI](https://pypi.org/project/fastapi/) — 验证版本与发布日期
- [Next.js endoflife.date](https://endoflife.date/nextjs) — Next.js 15 LTS 状态 + EOL 2026-10-21
- [Next.js Static Exports docs](https://nextjs.org/docs/app/guides/static-exports) — 静态导出能力与限制
- [Next.js issue #79380](https://github.com/vercel/next.js/issues/79380) — App Router + export + useParams 已知问题
- [pnpm 11 release notes / endoflife](https://eosl.date/eol/product/pnpm/) — 11.1.1 + Node 22 强制要求
- [shadcn/ui Tailwind v4 docs](https://ui.shadcn.com/docs/tailwind-v4) — v4 集成方式
- [uv Docker integration docs](https://docs.astral.sh/uv/guides/integration/docker/) — uv 镜像与多阶段构建
- [FastAPI Async Tests docs](https://fastapi.tiangolo.com/advanced/async-tests/) — pytest + httpx.AsyncClient + lifespan
- [Alembic async cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html) — async env.py 模式
- [FastAPI discussion #11345 — python-jose 移除推荐](https://github.com/fastapi/fastapi/discussions/11345)
- [pydantic-settings 2.14.1 on PyPI](https://pypi.org/project/pydantic-settings/)
- [mattermostautodriver 11.6.1 on PyPI](https://pypi.org/project/mattermostautodriver/)
- [pythonspeed.com base image 2026 analysis](https://pythonspeed.com/articles/base-image-python-docker-images/) — slim vs alpine 对比

### Supporting (MEDIUM confidence)
- [Building High-Performance Async APIs with FastAPI, SQLAlchemy 2.0, and Asyncpg (Leapcell)](https://leapcell.io/blog/building-high-performance-async-apis-with-fastapi-sqlalchemy-2-0-and-asyncpg) — 异步组合最佳实践
- [GLM 4.6 API Deployment Guide](https://www.digitalapplied.com/blog/glm-4-6-api-deployment-guide) — base_url 端点验证
- [Top 5 authentication solutions for FastAPI 2026 (WorkOS)](https://workos.com/blog/top-authentication-solutions-fastapi-2026)
- [aiosmtplib 5.1.0 docs](https://aiosmtplib.readthedocs.io/en/latest/) — port 465 + use_tls 配置

---

## Open Questions / Gaps（roadmap 阶段需明确）

1. **深链 URL 格式决策**：是否采纳 §2.3 方案 A（query string 代替 path param）？这影响后端 `build_deep_link` 函数 + 前端路由结构。**强烈推荐方案 A**，否则 Next.js 15 静态导出会变成 Phase 4 的高风险项。
2. **psycopg 连接池规模**：业务 asyncpg pool（≤10）+ LangGraph psycopg pool（≤10）= 单 flow-api 容器最多 20 个 PG 连接。Postgres 16 默认 `max_connections=100`，OK；如果 docker compose scale 多实例需调高。
3. **GLM 兼容接口 POC**：v1 启动前花 30 分钟验证 `openai` 包指向 `open.bigmodel.cn` 能否正常调用 glm-4.6（理论可行但**没有官方 SLA 保证**）。如果有兼容性问题就降级到 `zhipuai` SDK，业务代码改动量小。
4. **LangGraph checkpoint schema 与 alembic 关系**：明确文档化"`langgraph` schema 由 `await checkpointer.setup()` 管理，alembic 只管 `app` schema"，防止后续误把 LangGraph 表纳入迁移。

---

*Stack research for: AI-driven offboarding workflow system (LangGraph + FastAPI + Next.js 15)*
*Researched: 2026-05-16*
*Next review: 2026-08（季度滚动更新版本）*
