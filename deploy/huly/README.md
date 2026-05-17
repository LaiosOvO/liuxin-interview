# Huly 接入 — 部署 Runbook（Phase 8）

> 本文档是 Huly stack 在 192.168.2.44 的部署快速开始指南。
> 详细镜像清单与资源说明见 [HULY_IMAGES.md](./HULY_IMAGES.md)。

---

## 快速开始（3 步）

### 1. 拉镜像

```bash
cd /path/to/offboarding-flow
./scripts/pull_huly_images.sh
# 默认拉 HULY_VERSION=v0.7.423（约 7-9 GB）
```

### 2. 编辑 .env

```bash
cp .env.example .env  # 如未存在 .env

# 生成 Huly HMAC 密钥（必填）
openssl rand -hex 32  # → 填入 HULY_SERVER_SECRET
openssl rand -hex 16  # → 填入 HULY_BRIDGE_TOKEN

# 确认其他变量与本地环境一致：
#   HULY_URL=http://192.168.2.44:8087
#   HULY_ACCOUNTS_URL=http://192.168.2.44:3007
#   HULY_WORKSPACE=laios
```

### 3. 启动

```bash
# 启动 Huly stack（profile=huly-stack）
# 不影响现有 5 个 offboarding service（postgres / redis / flow-api / nginx / outline）
docker compose --profile huly-stack up -d

# 等 60 秒让 CockroachDB 初始化 + Elasticsearch warm up
sleep 60
docker compose --profile huly-stack ps
```

**预期**：14 个 `huly-*` container 全部 healthy。访问 http://192.168.2.44:8087 看到 Huly 登录页。

---

## 完整启动检查

```bash
# 1. 容器状态
docker compose --profile huly-stack ps
# 预期：所有 huly-* 容器 Status = healthy

# 2. CockroachDB SQL 可达
docker exec huly-cockroach cockroach sql --insecure -e "SELECT 1"

# 3. Elasticsearch 可达
curl http://192.168.2.44:19200/_cluster/health | jq .

# 4. MinIO console
open http://192.168.2.44:9092
# 用户名 minioadmin / 密码 minioadmin（默认；prod 务必改）

# 5. Huly Account API
curl http://192.168.2.44:3007/api/v1/ping

# 6. Huly Front
curl -I http://192.168.2.44:8087/
# 预期 200 / index.html

# 7. KVS health
curl http://192.168.2.44:8094/health
```

**首次安装必做**：在 Huly UI（http://192.168.2.44:8087）注册一个 admin 账号 + 创建 workspace `laios`。
Plan 04 的 `huly-bridge` sidecar 启动前必须这个 workspace 已存在。

---

## 验证现有服务无影响

```bash
# 不带 --profile 启动应仍只是 5 个现有 service
docker compose ps

# offboarding 后端 health 检查
curl http://192.168.2.44/api/health
# 预期 {"status":"ok"}

# nginx + 前端
open http://192.168.2.44/
```

---

## 故障排查

### 1. 镜像拉不到

```bash
# 单镜像测试网络
docker pull hardcoreeng/account:v0.7.423

# 检查 docker.io 是否可达
curl -v https://registry-1.docker.io/v2/

# 如内网无法到 docker.io，配置镜像加速器：
#   /etc/docker/daemon.json: { "registry-mirrors": ["https://docker.mirrors.ustc.edu.cn"] }
sudo systemctl restart docker
```

### 2. CockroachDB init 失败

```bash
# 看 init log
docker compose --profile huly-stack logs huly-cockroach | head -50

# 常见原因：volume 残留旧数据 → 完全重建
docker compose --profile huly-stack down
docker volume rm offboarding-flow_huly-cockroach-data
docker compose --profile huly-stack up -d
```

### 3. Elasticsearch OOM

```bash
# 看 ES 日志（OOM 一般有 java.lang.OutOfMemoryError）
docker compose --profile huly-stack logs huly-elastic | tail -50

# 修复：减小堆内存
# 编辑 docker-compose.yml huly-elastic env：ES_JAVA_OPTS=-Xms512m -Xmx512m
docker compose --profile huly-stack restart huly-elastic
```

### 4. Huly Front 502 / 503

通常是 transactor 或 account 未 ready。

```bash
# 检查依赖链
docker compose --profile huly-stack ps huly-account huly-transactor
# 任一非 healthy 时，等 30s 再访问 front

# 看 front 日志
docker compose --profile huly-stack logs huly-front | tail -30
```

### 5. SERVER_SECRET 校验失败 → 401

```bash
# 确认所有 huly-* service 的 SERVER_SECRET 一致
docker compose --profile huly-stack config | grep -A 1 SERVER_SECRET

# 若不一致，重建：
docker compose --profile huly-stack down
docker compose --profile huly-stack up -d
```

详见 [HULY_IMAGES.md](./HULY_IMAGES.md#已知-pitfall) 完整 Pitfall 列表。

---

## 关闭 / 清理

```bash
# 仅停止（保留卷）
docker compose --profile huly-stack stop

# 停止 + 删容器（保留卷）
docker compose --profile huly-stack down

# 完全清理（含卷 — 数据全删）
docker compose --profile huly-stack down -v
```

---

## 相关文档

- [HULY_IMAGES.md](./HULY_IMAGES.md) — 15 镜像清单 + 端口表 + 升级 / Pitfall
- [.env.example](../../.env.example) — `HULY_*` 6 个占位变量
- [docker-compose.yml](../../docker-compose.yml) — huly-stack profile 完整定义
- [上游 huly-selfhost](https://github.com/hcengineering/huly-selfhost) — 参考实现

---

*Last updated: 2026-05-17 — Phase 8 / HULY-01*
