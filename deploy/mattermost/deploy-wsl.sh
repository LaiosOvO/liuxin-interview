#!/usr/bin/env bash
# Mattermost LAN 部署脚本（在 WSL Ubuntu @ 192.168.2.44 内执行）
# 使用：cat deploy-wsl.sh | ssh GigaByte@192.168.2.44 'wsl -d Ubuntu -e bash -s'
# 或者：scp 到目标后 wsl bash deploy-wsl.sh

set -e

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/mattermost-docker}"
DOMAIN="${DOMAIN:-192.168.2.44}"
APP_PORT="${APP_PORT:-8065}"
CALLS_PORT="${CALLS_PORT:-8444}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?需要预先设置 POSTGRES_PASSWORD 环境变量}"

echo "== 1. clone mattermost/docker =="
if [ ! -d "$DEPLOY_DIR/.git" ]; then
  git clone --depth 1 https://github.com/mattermost/docker.git "$DEPLOY_DIR"
fi
cd "$DEPLOY_DIR"

echo "== 2. write .env =="
cat > .env <<ENVEOF
DOMAIN=${DOMAIN}
TZ=Asia/Shanghai
RESTART_POLICY=unless-stopped
POSTGRES_IMAGE_TAG=18-alpine
POSTGRES_DATA_PATH=./volumes/db/var/lib/postgresql/data
POSTGRES_USER=mmuser
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=mattermost
MATTERMOST_IMAGE=mattermost-team-edition
MATTERMOST_IMAGE_TAG=11.7.0
MATTERMOST_CONTAINER_READONLY=false
APP_PORT=${APP_PORT}
CALLS_PORT=${CALLS_PORT}
MATTERMOST_CONFIG_PATH=./volumes/app/mattermost/config
MATTERMOST_DATA_PATH=./volumes/app/mattermost/data
MATTERMOST_LOGS_PATH=./volumes/app/mattermost/logs
MATTERMOST_PLUGINS_PATH=./volumes/app/mattermost/plugins
MATTERMOST_CLIENT_PLUGINS_PATH=./volumes/app/mattermost/client/plugins
MATTERMOST_BLEVE_INDEXES_PATH=./volumes/app/mattermost/bleve-indexes
MM_BLEVESETTINGS_INDEXDIR=/mattermost/bleve-indexes
MM_SQLSETTINGS_DRIVERNAME=postgres
MM_SQLSETTINGS_DATASOURCE=postgres://\${POSTGRES_USER}:\${POSTGRES_PASSWORD}@postgres:5432/\${POSTGRES_DB}?sslmode=disable&connect_timeout=10
MM_SERVICESETTINGS_SITEURL=http://\${DOMAIN}:\${APP_PORT}
NGINX_IMAGE_TAG=alpine
NGINX_CONFIG_PATH=./nginx/conf.d
NGINX_DHPARAMS_FILE=./nginx/dhparams4096.pem
CERT_PATH=./volumes/web/cert/cert.pem
KEY_PATH=./volumes/web/cert/key-no-password.pem
HTTPS_PORT=443
HTTP_PORT=80
ENVEOF
chmod 600 .env

echo "== 3. fix Docker Desktop credsStore in WSL (避免非交互拉镜像报凭证错误) =="
mkdir -p ~/.docker
if [ -f ~/.docker/config.json ]; then
  python3 -c "
import json, os
p = os.path.expanduser('~/.docker/config.json')
c = json.load(open(p))
c.pop('credsStore', None)
c.pop('credHelpers', None)
json.dump(c, open(p, 'w'), indent=2)
" 2>/dev/null || echo '{}' > ~/.docker/config.json
fi

echo "== 4. create volume dirs + chown via throwaway alpine =="
mkdir -p ./volumes/app/mattermost/{config,data,logs,plugins,client/plugins,bleve-indexes}
mkdir -p ./volumes/db/var/lib/postgresql/data
docker run --rm -v "$(pwd)/volumes/app/mattermost:/vol" alpine:3 chown -R 2000:2000 /vol

echo "== 5. pull images =="
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml pull

echo "== 6. start =="
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d

sleep 5
echo "== 7. status =="
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml ps

echo
echo "==========================================================="
echo "部署完成，访问 http://${DOMAIN}:${APP_PORT}"
echo "首次访问会引导你创建系统管理员账号"
echo "==========================================================="
