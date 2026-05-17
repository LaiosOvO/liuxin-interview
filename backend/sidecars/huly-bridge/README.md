# Huly Bridge Sidecar

> Phase 8 / HULY-03 — Node sidecar：把 Python backend 的 HTTP 调用转换成 Huly TS SDK 调用

## 为什么需要 sidecar

Huly 平台只提供 TypeScript SDK（`@hcengineering/api-client`），Python 没有官方客户端。
本 sidecar 是 Python backend 与 Huly stack 之间的 **唯一桥梁**：

```
Python backend ──HTTP──→ huly-bridge (Node, port 7777) ──TS SDK──→ Huly stack
                                                                    ├─ huly-account:3007
                                                                    ├─ huly-transactor:3008
                                                                    └─ huly-front:8087
```

### 设计参考

参考实现：`hcengineering/platform:services/telegram-bot/pod-telegram-bot`
- `src/utils.ts` 的 `serviceToken()` 模式
- `src/start.ts` 的 `setMetadata` 初始化序

## 启动方式

### 本地 dev（不经 Docker）

```bash
cd backend/sidecars/huly-bridge
npm install              # 首次安装
cp ../../../.env .env    # 复制 env 文件（或手动写）
npm run dev              # tsx watch 热加载
```

### Docker（生产）

```bash
# 在仓库根目录
docker compose --profile huly --profile huly-stack up -d huly-bridge

# 单独构建测试
docker compose --profile huly build huly-bridge
```

## 端口 & endpoint 清单

| Endpoint | 方法 | 说明 | 实现状态 |
|----------|------|------|---------|
| `/healthz` | GET | 健康检查（含 Huly 连接状态） | ✅ 本 plan |
| `/api/im/send-dm` | POST | 发 DM 给单个 user | 🚧 Plan 05 |
| `/api/im/send-channel` | POST | 发消息到 channel | 🚧 Plan 05 |
| `/api/im/list-channels` | GET | 列 workspace channel | 🚧 Plan 05 |
| `/api/doc/create-folder` | POST | 在 teamspace 建文件夹 | 🚧 Plan 05 |
| `/api/doc/create-doc` | POST | 建 Document | 🚧 Plan 05 |
| `/api/doc/update-doc` | POST | 更新 Document | 🚧 Plan 05 |
| `/api/doc/link-collaborator` | POST | 加协作者 | 🚧 Plan 05 |

## 鉴权（Python backend → sidecar）

所有 `/api/*` endpoint 必须带 `X-Bridge-Token: ${HULY_BRIDGE_TOKEN}` header。

- token 由 `.env` 的 `HULY_BRIDGE_TOKEN` 注入（docker-compose 写好）
- `/healthz` 不需要 token（用于 healthcheck）
- token 不匹配返回 401

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 7777 | sidecar 监听端口 |
| `BRIDGE_TOKEN` | (required) | Python backend → sidecar 鉴权 token |
| `HULY_URL` | (required) | Huly transactor URL（如 `http://192.168.2.44:8087`） |
| `HULY_ACCOUNTS_URL` | (required) | Huly account API URL（如 `http://192.168.2.44:3007`） |
| `HULY_WORKSPACE` | (required) | 目标 workspace 名（如 `laios`） |
| `SERVER_SECRET` | (required) | Huly stack 共享 SERVER_SECRET（与 huly-account 同值） |
| `BACKEND_URL` | `http://flow-api:8000` | Plan 06 反向 listener 用 |
| `LOG_LEVEL` | `info` | `debug` / `info` / `warn` / `error` |

## 依赖说明 & 兜底路径

`@hcengineering/*` 包 v0.7.423 由 npm 公网拉取。

如 npm 公网拉不到（参考 RESEARCH §3.3.7 兜底路径）：
1. 改用 `pnpm install` —— pnpm 对 workspace:* 协议有更好支持
2. 从已部署的 huly-selfhost Docker image 提 tarball：
   ```bash
   docker run --rm hardcoreeng/account:v0.7.423 \
     tar czf - /usr/src/app/node_modules/@hcengineering > hcengineering.tgz
   ```
3. 把 tarball 解到本地 `node_modules/@hcengineering/`

## 与 Python backend 的关系

| 项 | 值 |
|----|----|
| sidecar 容器名 | `offboarding-huly-bridge` |
| sidecar 监听端口 | `7777:7777` |
| Python backend 调 sidecar URL | `http://huly-bridge:7777` |
| Python backend 鉴权 header | `X-Bridge-Token: ${HULY_BRIDGE_TOKEN}` |
| sidecar 调 backend URL | `http://flow-api:8000`（Plan 06 反向 listener 用） |

## 测试

```bash
npm test                # vitest run（全部测试）
npm run test:watch      # watch 模式
npm run test:coverage   # 含覆盖率报告
```

## 后续 plan

- **Plan 05**：实现 `/api/im/*` 与 `/api/doc/*` 真实路由（连 Huly TS SDK）
- **Plan 06**：反向 listener — sidecar 监听 Huly 消息推 backend
- **Plan 07**：seed 13 个 user 进 Huly workspace
