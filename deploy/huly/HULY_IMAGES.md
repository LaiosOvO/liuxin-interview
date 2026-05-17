# Huly 镜像清单（Phase 8 / HULY-01）

> 本文档描述 Huly 完整 stack 所需的 15 个 Docker 镜像、端口映射、资源占用与升级方法。
>
> 拉取脚本：`scripts/pull_huly_images.sh`（与本清单字段保持同步）
> compose 编排：`docker-compose.yml`（`profiles: ["huly-stack"]`）
> 上游参考：[huly-selfhost](https://github.com/hcengineering/huly-selfhost)

---

## 镜像总览

| # | 镜像 | 默认版本 | 类型 | 容器内端口 | 宿主端口（offboarding） | 用途 | RAM 预估 |
|---|------|---------|------|-----------|----------------------|------|---------|
| 1 | `hardcoreeng/account` | `${HULY_VERSION}` | 业务 | 3000 | `3007` | Account 服务（登录 / workspace 管理） | ~300M |
| 2 | `hardcoreeng/front` | `${HULY_VERSION}` | 业务 | 8080 | `8087` | 静态 SPA + Wiki UI（用户入口） | ~250M |
| 3 | `hardcoreeng/transactor` | `${HULY_VERSION}` | 业务 | 3333 | `3008` | Tx 协调器（主写入） | ~500M |
| 4 | `hardcoreeng/collaborator` | `${HULY_VERSION}` | 业务 | 3078 | `3009` | 协作编辑（CRDT / Yjs） | ~400M |
| 5 | `hardcoreeng/workspace` | `${HULY_VERSION}` | 业务 | — | （无） | Workspace 后台 worker | ~300M |
| 6 | `hardcoreeng/stats` | `${HULY_VERSION}` | 业务 | 4900 | （内网） | 指标聚合 | ~150M |
| 7 | `hardcoreeng/rekoni-service` | `${HULY_VERSION}` | 业务 | 4004 | （内网） | 文本提取 / OCR | ~500M |
| 8 | `hardcoreeng/fulltext` | `${HULY_VERSION}` | 业务 | 4700 | （内网） | 全文搜索网关 | ~300M |
| 9 | `hardcoreeng/hulykvs` | `${HULY_VERSION}` | 业务 | 8094 | `8094` | KV 元数据存储 | ~200M |
| 10 | `hardcoreeng/love` | `${HULY_VERSION}` | 业务 | — | （内网） | 视频通话信令（v1 可注释） | ~150M |
| 11 | `hardcoreeng/print` | `${HULY_VERSION}` | 业务 | — | （内网） | PDF / 导出渲染 | ~200M |
| 12 | `cockroachdb/cockroach:latest-v24.2` | v24.2 | 基础设施 | 26257 / 8080 | `26257` / `8888` | Huly 主数据库（PostgreSQL 兼容） | ~1G |
| 13 | `redpandadata/redpanda:v24.3.6` | v24.3 | 基础设施 | 9092 / 9644 | `19092` / `19644` | Kafka 兼容消息队列 | ~500M |
| 14 | `elasticsearch:7.14.2` | 7.14 | 基础设施 | 9200 | `19200` | 全文搜索引擎 | ~1.5G |
| 15 | `minio/minio:latest` | latest | 基础设施 | 9000 / 9001 | `9091` / `9092` | S3 兼容对象存储 | ~300M |

**合计：~6 GB 镜像 + ~5 GB 运行时 RAM。**

> Redis 复用项目独立 `offboarding-redis:6380`，Huly stack 默认不再起新 redis。
> 若后续启用 `hulypulse`（push 通知），再追加 `redis:7-alpine` 容器 + 端口 6381。

---

## 端口冲突表（与现有 offboarding stack 对照）

| 服务 | offboarding | Huly | 冲突？ |
|------|------------|------|--------|
| Postgres | 5433 | — | 否（Huly 用 CockroachDB） |
| Redis | 6380 | — | 否（Huly 复用 offboarding-redis） |
| flow-api | 8000 | — | 否 |
| Outline | 3001 | — | 否 |
| nginx | 80 | — | 否（Huly 走 8087 直出） |
| Mattermost | 8065 | — | 否 |
| MinIO（项目原有） | 9000 / 9001 | — | **是 → Huly MinIO 映射到 9091 / 9092** |
| CockroachDB | — | 26257 + 8888 | 否（新端口） |
| Redpanda | — | 19092 + 19644 | 否（避开 9092 给现有 MinIO） |
| Elasticsearch | — | 19200 | 否 |
| Huly Front | — | 8087 | 否 |
| Huly Account | — | 3007 | 否 |
| Huly Transactor | — | 3008 | 否 |
| Huly Collaborator | — | 3009 | 否 |
| Huly KVS | — | 8094 | 否 |
| huly-bridge（Plan 04） | — | 7777 | 否 |

---

## 如何拉镜像

### 一键全量

```bash
# 用 .env.example 默认版本 v0.7.423
./scripts/pull_huly_images.sh

# 验证：脚本末尾打印 15 个镜像本地存在
```

### 指定版本

```bash
HULY_VERSION=v0.7.500 ./scripts/pull_huly_images.sh
```

### 仅 dry-run 检查

```bash
./scripts/pull_huly_images.sh --dry-run
```

---

## 如何启动 Huly Stack

```bash
# 1. 先拉镜像（见上）
./scripts/pull_huly_images.sh

# 2. 编辑 .env 填占位（HULY_SERVER_SECRET / HULY_BRIDGE_TOKEN 等）
cp .env.example .env
openssl rand -hex 32  # 填入 HULY_SERVER_SECRET
openssl rand -hex 16  # 填入 HULY_BRIDGE_TOKEN

# 3. 启动 huly-stack（不影响现有 5 个 offboarding service）
docker compose --profile huly-stack up -d

# 4. 等 60s 让 CockroachDB / Elasticsearch 完成初始化，然后查询
docker compose --profile huly-stack ps

# 5. 浏览器访问 http://192.168.2.44:8087 看到 Huly 登录页
```

---

## 依赖与启动顺序

```
基础设施层（必须先 healthy）：
  huly-cockroach → huly-redpanda → huly-elastic → huly-minio
        ↓
业务核心层：
  huly-account (depends_on cockroach + minio)
        ↓
  huly-transactor (depends_on account)
        ↓
  huly-collaborator + huly-workspace + huly-fulltext + huly-kvs
        ↓
  huly-front (depends_on account + transactor + collaborator)
        ↓
辅助层（可独立）：
  huly-stats / huly-rekoni / huly-love / huly-print
        ↓
Plan 04 sidecar：
  huly-bridge (depends_on huly-front healthy)
```

**Plan 04 sidecar 启动前必须确保**：`huly-account` + `huly-front` + `huly-transactor` 三者都 healthy。

---

## 如何降级 / 升级

**版本一致性是硬约束**：11 个 `hardcoreeng/*` 镜像必须用同一 `${HULY_VERSION}`，
否则可能触发 schema mismatch（详见下方 Pitfall 1）。

### 升级流程

```bash
# 1. 全量 down
docker compose --profile huly-stack down

# 2. 改版本号（.env 中 HULY_VERSION=v0.7.500）
sed -i 's/HULY_VERSION=v0.7.423/HULY_VERSION=v0.7.500/' .env

# 3. 重新拉镜像
./scripts/pull_huly_images.sh

# 4. 重新启动
docker compose --profile huly-stack up -d

# 5. 观察 transactor 日志确认 schema migration 成功
docker compose --profile huly-stack logs -f huly-transactor | grep -i "migration\|schema"
```

### 降级注意

- CockroachDB 数据卷 (`huly-cockroach-data`) 含 schema，降级需先 `docker volume rm` 后重新 init
- Elasticsearch index `huly_storage_index` 在新版本不兼容时会自动重建
- MinIO 对象存储兼容性最强，可跨版本保留

---

## 已知 Pitfall

### Pitfall 1: SERVER_SECRET 必须一致

`account / transactor / collaborator / workspace / front / stats / fulltext / kvs / rekoni` 等所有业务服务都用同一个 `SERVER_SECRET`（即 .env 中 `HULY_SERVER_SECRET`）做 HMAC token 签名。
任何一个服务密钥不一致都会导致：
- `account` 颁发的 token 在 `transactor` 验签失败 → 401
- WebSocket 连接被踢

修复：检查 `docker compose config` 输出，确认所有 huly-* service 的 `SERVER_SECRET` env 值一致。

### Pitfall 2: 版本不一致 → schema mismatch

`transactor` 与 `workspace` 版本不一致时，workspace migration 脚本可能跑出错误 schema。
**修复**：升级时务必把 11 个 hardcoreeng 镜像一起改版本号，不要单独升级某个服务。

### Pitfall 3: Elasticsearch 内存不足

ES 7.14.2 默认 `-Xms1g -Xmx1g`，宿主机若总 RAM < 8G 容易 OOM。
**修复**：在 .env 中加 `ES_JAVA_OPTS=-Xms512m -Xmx512m`，或扩容宿主机内存。

### Pitfall 4: CockroachDB 首次启动慢

CockroachDB 初始化 schema 需 20-40s，期间 `account` 容器会反复 restart。
**修复**：用 healthcheck + `depends_on: condition: service_healthy`，等 cockroach healthy 才启动 account。

### Pitfall 5: MinIO 端口与项目原 MinIO 冲突

项目已有 `offboarding-minio` 用 9000/9001；Huly MinIO 必须避开这两个端口。
**修复**：本 plan 已映射到 `9091:9000` + `9092:9001`，与原项目无冲突。

---

## 与项目其他文档关联

| 文档 | 关联点 |
|------|--------|
| `deploy/huly/README.md` | 部署 runbook（3 步快速开始） |
| `.env.example` | 6 个 `HULY_*` 占位变量 |
| `.planning/phases/08-huly-abstraction/08-RESEARCH.md` | Huly 选型 + Pitfall 调研 |
| `.planning/phases/08-huly-abstraction/08-CONTEXT.md` | Phase 8 实现决策 |
| `.planning/phases/08-huly-abstraction/08-04-PLAN.md` | huly-bridge sidecar 实现（后续 plan） |

---

*Last updated: 2026-05-17 — Phase 8 Plan 03 HULY-01*
