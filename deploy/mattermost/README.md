# Mattermost LAN 部署（192.168.2.44）

> 目标：在 GigaByte Windows 11 主机 `192.168.2.44` 上跑 Mattermost Team Edition，作为 AI 离职流程系统的 IM 通道 + 轻量 HR 目录。

## 环境画像

| 项 | 值 |
| --- | --- |
| 宿主机 | Windows 11 24H2 (build 26200)，hostname `WIN-D2N8I1NRO0V` |
| LAN IP | `192.168.2.44` |
| SSH 用户 | `GigaByte`（本地管理员，已加 Mac 公钥到 `C:\ProgramData\ssh\administrators_authorized_keys`）|
| Docker Desktop | 29.4.3 + WSL2 后端 |
| WSL 发行版 | Ubuntu (default)，WSL 内用户 `laios`，已在 `docker` 组 |
| 部署目录 | `/home/laios/mattermost-docker/`（WSL Ubuntu 内）|

> Windows OpenSSH 默认会忽略管理员账号的 `~/.ssh/authorized_keys`，必须放到 `C:\ProgramData\ssh\administrators_authorized_keys` 才生效。

## 架构

```
Mac/手机 (LAN) ──→ 192.168.2.44:8065 (Windows host)
                         │ (Docker Desktop 端口映射)
                         ▼
                  Mattermost 容器 (在 Docker Desktop WSL2 后端)
                         ▲
        从 WSL Ubuntu 用 `docker compose` 编排
        (bind-mount /home/laios/mattermost-docker/volumes/...)
```

为什么走 WSL Ubuntu 而不是 Windows 原生：

- chown 2000:2000（Mattermost 容器需要的属主）在 Windows 文件系统上行不通
- bash heredoc / compose override 都是 Linux 原生写法
- WSL2 + Docker Desktop 集成后，`docker compose` 在 WSL 里运行等价于在 Windows 上运行，容器实际由 docker-desktop 后端调度，端口照样发布到 Windows 宿主

## 配置

`.env`（**真实部署的版本不在 git 里**，模板见 `.env.example`），关键值：

- `DOMAIN=192.168.2.44`
- `APP_PORT=8065`（HTTP 直出，不走 nginx）
- `CALLS_PORT=8444`（避开常见占用）
- `MATTERMOST_IMAGE=mattermost-team-edition`（开源版，无 license）
- `MM_SERVICESETTINGS_SITEURL=http://192.168.2.44:8065`
- `MM_SQLSETTINGS_DATASOURCE=postgres://mmuser:<pwd>@postgres:5432/mattermost?sslmode=disable&connect_timeout=10`

`docker-compose.yml` + `docker-compose.without-nginx.yml`（官方仓库自带），仅暴露：

- `8065/tcp`（Mattermost HTTP）
- `8444/udp` + `8444/tcp`（Calls，可选）

Postgres 不发布到宿主，只在 docker 内网。

## 部署步骤（已在 WSL Ubuntu 内执行）

```bash
# 1. clone
git clone --depth 1 https://github.com/mattermost/docker.git ~/mattermost-docker
cd ~/mattermost-docker

# 2. 写 .env（按本目录 .env.example 模板，密码用 secrets 生成）
# cat > .env <<EOF ... EOF

# 3. 解决 Docker Desktop credsStore 在 WSL 非交互调用失败
mkdir -p ~/.docker
python3 -c "import json; p='/home/laios/.docker/config.json'; c=json.load(open(p)); c.pop('credsStore',None); c.pop('credHelpers',None); json.dump(c, open(p,'w'), indent=2)"

# 4. 创建数据卷 + chown（用一次性 alpine，避免 sudo）
mkdir -p ./volumes/app/mattermost/{config,data,logs,plugins,client/plugins,bleve-indexes}
mkdir -p ./volumes/db/var/lib/postgresql/data
docker run --rm -v "$(pwd)/volumes/app/mattermost:/vol" alpine:3 chown -R 2000:2000 /vol

# 5. 启动
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d

# 6. 验证
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml ps
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.2.44:8065
```

## 首次访问

1. 浏览器打开 `http://192.168.2.44:8065`
2. 第一次访问会被引导创建系统管理员账号（用户名 + 邮箱 + 密码）
3. 创建初始 team（如 `liuxin-hr`），后续 AI 离职流程系统的通知都走这个 team 的 channels

## 给离职流程系统准备的 Bot

进入 Mattermost 后台：

1. **System Console** → **Integrations** → **Bot Accounts** → **Enable Bot Account Creation: true**
2. **Integrations** → **Bot Accounts** → **Add Bot Account**
   - Username: `offboarding-bot`
   - Display Name: `离职流程 Bot`
3. 创建后会拿到 **Personal Access Token**，**只显示一次**，保存到 `hr/.env`：`MATTERMOST_BOT_TOKEN=...`
4. 给 Bot 加 Team / Channel 权限：在目标 team / channel **Add Members** 把 bot 加进去

## 给离职流程系统准备的 Incoming Webhook

1. **Integrations** → **Incoming Webhooks** → **Add**
2. Channel: 选目标频道（如 `#hr-offboarding`）
3. 拿到 Webhook URL：`http://192.168.2.44:8065/hooks/<hash>`
4. 保存到 `hr/.env`：`MATTERMOST_WEBHOOK_URL=...`

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `docker pull` 报 `A specified logon session does not exist` | Docker Desktop credsStore 在 WSL 非交互调用失败 | 清掉 `~/.docker/config.json` 的 `credsStore` 字段 |
| 容器起来了但 LAN 上访问不到 `8065` | Windows Defender Firewall 拦截 | 在 Windows 上 `New-NetFirewallRule -DisplayName "Mattermost 8065" -Direction Inbound -LocalPort 8065 -Protocol TCP -Action Allow` |
| chown 报 permission denied | 当前用户不在 docker 组或没用 alpine 容器做 chown | 走 §部署步骤 #4 那个 alpine docker run |
| `wsl -d Ubuntu` 报找不到分发 | 默认分发是 docker-desktop 而非 Ubuntu | `wsl --set-default Ubuntu` |
| Mattermost 启动后报 DB 连接失败 | postgres 还没起完 | 重启 mattermost 容器：`docker compose restart mattermost` |

## 回滚

```bash
cd ~/mattermost-docker
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml down
# 数据保留（在 ./volumes/）
# 完全清理：
# docker compose ... down -v && rm -rf ./volumes
```

## 数据备份（运行后再做）

```bash
# 备份 postgres
docker compose exec postgres pg_dump -U mmuser mattermost | gzip > backup-$(date +%Y%m%d).sql.gz

# 备份 mattermost 配置 + 上传文件
tar czf mm-data-$(date +%Y%m%d).tar.gz ./volumes/app/mattermost/{config,data}
```
