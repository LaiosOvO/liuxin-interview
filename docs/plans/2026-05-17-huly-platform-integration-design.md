# Huly Platform 接入设计 — 让 offboarding-flow 同时兼容 Huly 作为 IM + 协作文档系统

> **日期**：2026-05-17
> **目标**：在已有 Mattermost / Outline / 飞书 / 企微 / 钉钉 之外，再加 Huly Platform 作为可切换的 IM + 协作文档 Provider。
> **状态**：设计稿
> **关联**：`README.md` §3（DocProvider / IMProvider 抽象）、[`agent-builder/docs/plans/2026-05-17-im-bot-abstraction-design.md`](../../../agent-builder/docs/plans/2026-05-17-im-bot-abstraction-design.md)

---

## 1. 背景

[Huly Platform](https://github.com/hcengineering/platform) 是一体化办公平台（Linear / Jira / Slack / Notion / Motion 替代品），自带：

- **Chat / Messenger** — 可以替代 Mattermost 作为 IM 通道
- **Docs / Wiki** — 可以替代 Outline 作为协作文档归档目标
- **Project Management / CRM / HRM / ATS / QMS** — 与本系统无直接关联，但同一账号体系

接入 Huly 后：**一套 Huly 部署 = MM + Outline 二合一**，对于已经在用 Huly 的客户（包括内网 / 私有部署）零额外学习成本。

---

## 2. 现状回顾：本系统已有的 Provider 抽象

`backend/src/offboarding_flow/providers/`：

```
base.py                — DocProvider / IMProvider Protocol（Python typing.Protocol）
factory.py             — get_doc_provider() / get_im_provider() @lru_cache 单例
outline_provider.py    — Outline（真接入）
mattermost_provider.py — Mattermost（真接入）
lark_provider.py       — 飞书（真接入，tenant_access_token 缓存）
wecom_provider.py      — 企微（stub 抛 ProviderError）
dingtalk_provider.py   — 钉钉（stub）
```

`workers/mattermost_listener.py` — WS 长连接 + 事件分发。

接入 Huly 的核心动作：**加 2 个新 Provider + 1 个 listener**，**不改业务代码**。

---

## 3. 关键技术约束（Huly 接入的难点）

| 维度 | Mattermost | Outline | Huly |
|---|---|---|---|
| 鉴权方式 | Bot token (X-Header) | API token (Bearer) | **OAuth/OIDC + JWT**，bot 凭证靠 account service 签发 |
| 客户端 SDK | 多语言（Python `mattermostautodriver`） | REST（自己写 httpx 包装） | **只有 TypeScript SDK**（`@hcengineering/api-client`，WS-based） |
| 协议 | REST + WebSocket | REST | **WebSocket Tx 事件流**（自家私有协议，非 JSON-RPC 标准） |
| Bot/Webhook | Bot account + Outgoing Webhook + Slash | API token，不支持 webhook | 仅 GitHub 集成支持 webhook；其他渠道通过外部 bridge（如 Telegram bot） |
| Python 直接接入 | ✅ | ✅ | ❌（需 sidecar 或 MCP 包装） |

**结论**：Python 后端**无法直接**用官方 SDK 接 Huly。需要：

- **方案 A — Node.js sidecar**：起一个轻量 Node 服务跑 `@hcengineering/api-client`，对内暴露 HTTP API + 转发 WS 事件到 Python 后端
- **方案 B — 第三方 MCP 包装**：用 `mcpmarket.com/server/huly` 提供的 HTTP REST 包装
- **方案 C — 自己 reverse 协议**：Python 实现 Huly WS Tx 协议（成本最高，不推荐）

**推荐方案 A**：

- 成本：Node 镜像 + 一个 200 行 Express 服务
- 优势：用官方 SDK，跟 Huly 升级风险最小；架构与现有 `mattermost_listener` 一致（Python listener pattern）
- 劣势：多一个进程要维护

---

## 4. 架构图（方案 A — Node sidecar）

```
┌────────────────────────────────────────────────────────────────────┐
│ offboarding-flow backend (Python FastAPI)                          │
│                                                                    │
│  IMProvider Protocol                                               │
│       │                                                            │
│       ├─→ huly_im_provider.py  ────────┐                          │
│       │   send_dm / post_to_channel    │  HTTP POST               │
│       │   ensure_user_in_channel       │  http://huly-bridge:7777 │
│       │                                ▼                          │
│  DocProvider Protocol         ┌─────────────────────────────┐    │
│       │                       │ huly-bridge (Node.js sidecar)│    │
│       ├─→ huly_doc_provider   │  Express HTTP API           │    │
│       │   create_document     │     ↕                       │    │
│       │   ensure_users        │  @hcengineering/api-client   │    │
│                               │     ↕  WebSocket             │    │
│  workers/huly_listener.py     │     ↓                       │    │
│       (or HTTP poll)          │  Huly Transactor (WS)        │    │
│       │                       └─────────────────────────────┘    │
│       │ 反向：sidecar 把 Huly chat msg 通过 HTTP POST 推回 backend │
│       │ POST /api/internal/huly/event                              │
│       ↓                                                            │
│  bot_service.handle_message()  ← 复用同一套 dispatcher              │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ↓
┌────────────────────────────────────────────────────────────────────┐
│ Huly Platform (一体化，self-host)                                  │
│                                                                    │
│  nginx (8087)                                                      │
│   ├── front-end UI                                                 │
│   ├── account service (3000) — OAuth / OIDC                        │
│   ├── transactor (WebSocket)                                       │
│   ├── collaborator                                                 │
│   ├── workspace / fulltext / stats / kvs                           │
│   └── rekoni (OCR)                                                 │
│                                                                    │
│  外部依赖:                                                          │
│   ├── CockroachDB                                                  │
│   ├── Redpanda (Kafka)                                             │
│   ├── MinIO (S3)                                                   │
│   └── Elasticsearch 7.14                                           │
└────────────────────────────────────────────────────────────────────┘
```

---

## 5. 需要拉取的 Docker 镜像

### 5.1 Huly 核心服务镜像（hardcoreeng/*，版本变量 `HULY_VERSION`，最新稳定取 `v0.6.500` 或随官方）

```bash
export HULY_VERSION=v0.6.500   # 实际看 https://github.com/hcengineering/huly-selfhost/releases

# 核心微服务
docker pull hardcoreeng/transactor:${HULY_VERSION}      # WebSocket Tx 网关（最关键，对外暴露 WS）
docker pull hardcoreeng/account:${HULY_VERSION}         # 账号 / OAuth / OIDC
docker pull hardcoreeng/workspace:${HULY_VERSION}       # workspace 管理
docker pull hardcoreeng/front:${HULY_VERSION}           # 前端静态资源
docker pull hardcoreeng/collaborator:${HULY_VERSION}    # 协作文档（Yjs CRDT）
docker pull hardcoreeng/fulltext:${HULY_VERSION}        # 全文搜索 worker
docker pull hardcoreeng/stats:${HULY_VERSION}           # 监控统计
docker pull hardcoreeng/hulykvs:${HULY_VERSION}         # KV store (8094)
docker pull hardcoreeng/rekoni-service:${HULY_VERSION}  # OCR / 文档解析
```

### 5.2 基础设施镜像（与 Huly 同 stack 部）

```bash
docker pull nginx:1.21.3                              # 反代（Huly 内置 conf）
docker pull cockroachdb/cockroach:latest-v24.2        # 主数据库（替代 PG）
docker pull docker.redpanda.com/redpandadata/redpanda:v24.3.6  # Kafka 兼容
docker pull minio/minio                                # S3 兼容对象存储
docker pull elasticsearch:7.14.2                       # 全文搜索
```

### 5.3 本系统新增的 sidecar 镜像（自建）

```bash
# 自建 Node.js sidecar，参考 backend/sidecars/huly-bridge/Dockerfile（待写）
docker build -t offboarding-flow/huly-bridge:latest ./backend/sidecars/huly-bridge
```

### 5.4 一键全量拉取脚本

```bash
#!/bin/bash
set -e
export HULY_VERSION=v0.6.500

for img in transactor account workspace front collaborator fulltext stats hulykvs rekoni-service; do
  docker pull hardcoreeng/${img}:${HULY_VERSION}
done

docker pull nginx:1.21.3
docker pull cockroachdb/cockroach:latest-v24.2
docker pull docker.redpanda.com/redpandadata/redpanda:v24.3.6
docker pull minio/minio
docker pull elasticsearch:7.14.2

echo "✓ 全部镜像就绪，共 $(docker images | grep -E 'hardcoreeng|cockroach|redpanda|elasticsearch|minio/minio' | wc -l) 个"
```

保存为 `scripts/pull_huly_images.sh`。在 `192.168.2.44` 上跑一次（约 4-6 GB 下载）。

---

## 6. 代码改动点（最小可用版）

### 6.1 新增文件

| 文件 | 行数估算 | 作用 |
|---|---|---|
| `backend/src/offboarding_flow/providers/huly_doc_provider.py` | ~120 | 实现 `DocProvider` Protocol，调 huly-bridge HTTP |
| `backend/src/offboarding_flow/providers/huly_im_provider.py` | ~150 | 实现 `IMProvider` Protocol，调 huly-bridge HTTP |
| `backend/src/offboarding_flow/workers/huly_listener.py` | ~100 | 接收 huly-bridge POST 的 chat 事件 → 转 bot_service.dispatch（**或**让 bridge 直接 POST 到 `/api/internal/huly/event` 由 FastAPI 路由处理） |
| `backend/src/offboarding_flow/api/internal_huly.py` | ~60 | FastAPI 路由 `POST /api/internal/huly/event`，鉴权 + 转 bot_service |
| `backend/sidecars/huly-bridge/index.ts` | ~250 | Node 服务：起 Express + 连 Huly WS + 把消息 POST 回 backend |
| `backend/sidecars/huly-bridge/Dockerfile` | ~15 | Node 18 alpine + tsx |
| `backend/sidecars/huly-bridge/package.json` | ~20 | `@hcengineering/api-client` + `express` + `tsx` |
| `scripts/pull_huly_images.sh` | ~20 | 一键拉镜像 |

### 6.2 修改文件

| 文件 | 改动 |
|---|---|
| `providers/factory.py` | `get_doc_provider()` / `get_im_provider()` 加 `case "huly":` 返回 Huly provider 实例 |
| `config.py` | 新增 Settings 字段：`huly_url` / `huly_account_email` / `huly_account_password` / `huly_workspace` / `huly_bridge_url` |
| `.env.example` | 加 Huly 占位变量 |
| `docker-compose.yml` | 加 `huly-bridge` service + 可选 `huly-stack` profile（用 `--profile huly` 启用） |
| `main.py` | 启动期判 `IM_PROVIDER=huly` 则启 `huly_listener`（替代 `mattermost_listener`） |

### 6.3 Provider 切换 = 改 `.env`

```ini
# .env
DOC_PROVIDER=huly             # outline | lark | wecom | dingtalk | huly
IM_PROVIDER=huly              # mattermost | lark | wecom | dingtalk | huly

HULY_URL=http://192.168.2.44:8087
HULY_BRIDGE_URL=http://huly-bridge:7777    # 内网 docker-compose 网络名
HULY_ACCOUNT_EMAIL=bot@offboarding.local
HULY_ACCOUNT_PASSWORD=changeme_in_real_env  # 真值只走 env，不进 git
HULY_WORKSPACE=laios
```

> **凭证安全**：`HULY_ACCOUNT_PASSWORD` 必须从 env 注入，不进 `.env.example`（只放占位）。pre-commit gitleaks 已会拦截。

---

## 7. huly-bridge 关键代码草稿（Node.js）

```typescript
// backend/sidecars/huly-bridge/index.ts
import express from 'express';
import { connect } from '@hcengineering/api-client';   // 官方 SDK
import * as chunter from '@hcengineering/chunter';     // chat / channels

const app = express();
app.use(express.json());

const BACKEND_URL = process.env.BACKEND_URL!;          // http://backend:8000
const HULY_URL = process.env.HULY_URL!;
const EMAIL = process.env.HULY_ACCOUNT_EMAIL!;
const PASS = process.env.HULY_ACCOUNT_PASSWORD!;
const WS = process.env.HULY_WORKSPACE!;

const client = await connect(HULY_URL, { email: EMAIL, password: PASS, workspace: WS });

// 1. 接 backend 的 send_dm / post_channel / create_doc 请求
app.post('/api/im/send_dm', async (req, res) => {
  const { to_username, message } = req.body;
  const targetAccount = await client.findOne(account.class.Account, { email: `${to_username}@demo.local` });
  const dmChannel = await client.findOne(chunter.class.DirectMessage, { members: [client.user(), targetAccount._id] });
  await client.createDoc(chunter.class.Message, dmChannel._id, { text: message });
  res.json({ ok: true });
});

app.post('/api/doc/create', async (req, res) => {
  const { title, content_md, collaborator_emails } = req.body;
  // 调 collaborator service 创建 Yjs 文档
  const doc = await client.createDoc(documents.class.Document, ..., { title, content: content_md });
  res.json({ ok: true, url: `${HULY_URL}/workbench/${WS}/document/${doc._id}` });
});

// 2. 订阅 Huly chat 事件 → 转 POST 给 backend
client.query(chunter.class.Message, {}, async (msgs) => {
  for (const msg of msgs) {
    if (msg.createdBy === client.user()._id) continue;  // 跳自己防死循环
    await fetch(`${BACKEND_URL}/api/internal/huly/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Bridge-Token': process.env.BRIDGE_TOKEN },
      body: JSON.stringify({
        sender_email: await getEmail(msg.createdBy),
        channel_id: msg.attachedTo,
        channel_type: msg.attachedToClass === chunter.class.DirectMessage ? 'D' : 'O',
        message: msg.text,
        ts: msg.createdOn,
      }),
    });
  }
});

app.listen(7777, () => console.log('huly-bridge listening on 7777'));
```

backend Python 侧接收：

```python
# backend/src/offboarding_flow/api/internal_huly.py
from fastapi import APIRouter, Depends, HTTPException, Request
from offboarding_flow.services.bot_service import dispatch_message

router = APIRouter()

@router.post('/api/internal/huly/event')
async def huly_event(req: Request):
    if req.headers.get('X-Bridge-Token') != settings.huly_bridge_token:
        raise HTTPException(401)
    payload = await req.json()
    # 复用与 mattermost_listener 一样的 dispatch 逻辑
    await dispatch_message(
        sender_username=payload['sender_email'].split('@')[0],   # 取 username 段
        channel_id=payload['channel_id'],
        channel_type=payload['channel_type'],
        message=payload['message'],
    )
    return {'ok': True}
```

> ✨ **关键洞察**：把 `mattermost_listener.py` 里的 dispatch 逻辑（行 175 之后）提取成独立函数 `dispatch_message(sender, channel, ...)`，让 MM listener 和 Huly listener 都调它。**这就是已有的 README §3 "username 跨系统对齐"模式的复用**——sender email 取 username 段直查 users 表。

---

## 8. docker-compose.yml 集成段

```yaml
# docker-compose.yml — 加在末尾，用 profile 控制按需启动
services:
  # ... 已有的 offboarding-postgres / offboarding-redis / backend / frontend / nginx ...

  huly-bridge:
    profiles: ["huly"]
    build: ./backend/sidecars/huly-bridge
    image: offboarding-flow/huly-bridge:latest
    environment:
      HULY_URL: ${HULY_URL}
      HULY_ACCOUNT_EMAIL: ${HULY_ACCOUNT_EMAIL}
      HULY_ACCOUNT_PASSWORD: ${HULY_ACCOUNT_PASSWORD}
      HULY_WORKSPACE: ${HULY_WORKSPACE}
      BACKEND_URL: http://backend:8000
      BRIDGE_TOKEN: ${HULY_BRIDGE_TOKEN}
    ports:
      - "7777:7777"
    networks:
      - offboarding-net
    depends_on:
      - backend
    restart: unless-stopped

  # —— Huly stack（可选，独立部更稳；同机部署用 --profile huly-stack）——
  huly-cockroach:
    profiles: ["huly-stack"]
    image: cockroachdb/cockroach:latest-v24.2
    command: start-single-node --insecure
    ports: ["26257:26257"]
    volumes: ["huly-cockroach-data:/cockroach/cockroach-data"]

  huly-redpanda:
    profiles: ["huly-stack"]
    image: docker.redpanda.com/redpandadata/redpanda:v24.3.6
    command: redpanda start --smp 1 --overprovisioned

  huly-elastic:
    profiles: ["huly-stack"]
    image: elasticsearch:7.14.2
    environment:
      discovery.type: single-node
      ES_JAVA_OPTS: -Xms512m -Xmx512m

  huly-minio:
    profiles: ["huly-stack"]
    image: minio/minio
    command: server /data --console-address ":9098"
    ports: ["9097:9000", "9098:9098"]

  huly-transactor:
    profiles: ["huly-stack"]
    image: hardcoreeng/transactor:${HULY_VERSION:-v0.6.500}
    environment:
      SERVER_PORT: 3333
      DB_URL: "postgresql://root@huly-cockroach:26257/defaultdb?sslmode=disable"
      # ... 其余按 huly-selfhost compose.yml 抄
    depends_on:
      - huly-cockroach
      - huly-elastic
      - huly-minio

  huly-front:
    profiles: ["huly-stack"]
    image: hardcoreeng/front:${HULY_VERSION:-v0.6.500}
    ports: ["8087:8080"]
    environment:
      SERVER_PORT: 8080
      TRANSACTOR_URL: ws://huly-transactor:3333

  # ... account / workspace / collaborator / fulltext / stats / hulykvs / rekoni-service 同样照抄
```

启动方式：

```bash
# 只跑业务（默认）
docker compose up -d

# 业务 + huly-bridge（已有外部 Huly 部署）
docker compose --profile huly up -d

# 业务 + huly-bridge + Huly 全栈（同一台机器）
docker compose --profile huly --profile huly-stack up -d
```

---

## 9. 身份对齐方案（最关键的一段）

按 [README §3](../../README.md)，本系统已经用 `username` 作为跨系统主键。Huly 加入时：

| 维度 | 业务 DB | Mattermost | Outline | Huly |
|---|---|---|---|---|
| 主键 | `username` (`it.charlie`) | `username` (同 seed) | `email` (`it.charlie@demo.local`) | `email` (Huly 用 email 当主键) |

**接入 Huly 的对齐策略**：

1. 业务 DB `users` 表的 `email` 字段格式 `{username}@demo.local`（已有）
2. seed Huly 时按业务 DB 批量调 Huly account API 创建账号，email 用同样格式
3. huly-bridge 收到 Huly chat 事件后，`payload.sender_email.split('@')[0]` 提取 username → 与本地 users.username 完全对齐
4. handover doc 创建时 `collaborator_emails = [user.email for user in collaborators]` 直接传 email

**修改点**：仅 `huly_doc_provider.ensure_users()` 和 `huly_im_provider.send_dm()` 内部把 username 映射回 email，然后调 sidecar。

---

## 10. listener 模式对比

| 模式 | Mattermost | Huly |
|---|---|---|
| 进程数 | 1（Python WS） | 2（Python backend + Node bridge） |
| 协议层 | mattermostautodriver 直接 WS | bridge WS 订阅 → HTTP POST |
| 启动顺序 | listener 由 `main.py lifespan` 起 | bridge 独立 docker service，backend 仅起 internal API 接收 POST |
| 鉴权 | bot_token（env） | bridge 用 account email/pwd 登录拿 token；backend ↔ bridge 用 BRIDGE_TOKEN 共享 secret |

`main.py` 改动（约 20 行）：

```python
# main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    listener = None
    if settings.im_provider == 'mattermost':
        listener = MattermostListener(settings)
        await listener.start()
    elif settings.im_provider == 'huly':
        # Huly 走 sidecar 模式，backend 仅注册路由接收 webhook
        # 启动期可选 health-check sidecar 是否 alive
        await _wait_huly_bridge_ready(settings.huly_bridge_url)
    # else: lark/wecom/dingtalk 各自模式

    yield

    if listener is not None:
        await listener.stop()
```

---

## 11. Phase 拆分

| Phase | 任务 | 验收 |
|---|---|---|
| H-1 | sidecar MVP：bridge 仅实现 `send_dm` + `create_document` 两个最小 API | curl 测两个 API 真往 Huly 写 |
| H-2 | Provider 移植：`huly_doc_provider` + `huly_im_provider` 通过 sidecar 走通 handover doc 生成 | 起一个流程 → handover doc 真出现在 Huly Wiki |
| H-3 | 反向事件流：bridge 订阅 Huly chat → POST backend → bot_service.dispatch | Huly 里 @bot 我要离职 → 真起流程 |
| H-4 | `dispatch_message` 重构：提取 mattermost_listener 行 175+ 逻辑为独立函数，MM / Huly 共用 | MM + Huly 双 listener 同时跑互不影响 |
| H-5 | docker-compose 集成 + 启动文档 + E2E（用 browser-harness 截 Huly UI） | `--profile huly` 跑通完整流程 |
| H-6 | identity sync：seed 脚本批量为业务 DB 13 个 user 在 Huly 建账号 | `python scripts/seed_huly_users.py` 一键完成 |

---

## 12. 风险 + 兜底

| 风险 | 缓解 |
|---|---|
| Huly TS SDK 升级 break sidecar | 锁版本 `@hcengineering/api-client@x.y.z`，CI 跑契约测试 |
| Node sidecar 挂掉 → backend 收不到事件 | `restart: unless-stopped` + healthcheck + alert，bridge log 持久化 |
| Huly account 密码进 git | 与 MM/Outline 一致，仅 env 注入，gitleaks 拦 |
| Huly 全栈占资源（CockroachDB + ES + Redpanda 同机起约 4-6GB RAM） | 内网生产建议独立部 Huly，本系统仅 sidecar 共驻 |
| Huly chat 消息流量大触发频繁 LLM intent | 与 MM 一致，rate-limit + 仅触发条件命中调 LLM |
| Bot 在 Huly 没有 channel 加入权限 | seed 时用 admin token 让 bot 自动加入 announcements / 各部门 channel |

---

## 13. 验收 E2E（用 browser-harness）

参考 [`docs/meeting-summary-e2e-test-2026-05-17.md`](../meeting-summary-e2e-test-2026-05-17.md) 的 NL 路由测试模式：

1. 在 Huly UI 打开 bot DM
2. it.charlie 发 "@offboarding-bot 我要离职"
3. 截图：bot 回执 11 节点清单（与 MM 截图 20-mm-bot-resign 对照）
4. 推进流程 → handover doc 真写入 Huly Wiki，按员工分文件夹（Huly 用 `Space` 概念）
5. 截图：Huly Wiki 看到 `离职 · it.charlie` Space + 9 个节点交接文档

---

## 14. 总结：3 步骤完成 Huly 接入

1. **拉镜像**：跑 `scripts/pull_huly_images.sh`（9 个 hardcoreeng/* + 5 个基础设施）
2. **加 sidecar**：在 `backend/sidecars/huly-bridge/` 写 Node 服务（约 250 行 TS）
3. **加 2 个 Provider + 1 个内部 API + docker-compose profile**：业务代码改动 < 300 行

完成后切换 = 改 `.env` 两行：

```ini
DOC_PROVIDER=huly
IM_PROVIDER=huly
```

> **零业务代码改动** — 这就是 [README §3 三系统身份同步](../../README.md) + Provider 抽象的红利。

---

## 参考资料

- [Huly Platform](https://github.com/hcengineering/platform)
- [huly-selfhost](https://github.com/hcengineering/huly-selfhost)
- [Huly docs — API & tools](https://docs.huly.io/getting-started/api-tools/)
- [Does Huly have API? #6996](https://github.com/hcengineering/platform/issues/6996)
- [huly.core/packages/api-client](https://github.com/hcengineering/huly.core/blob/main/packages/api-client/README.md)
- [Huly MCP server (HTTP REST 包装备选)](https://mcpmarket.com/server/huly)
