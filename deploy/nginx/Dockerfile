## nginx 镜像 — 反向代理 + 静态前端服务
## REQ: DEPLOY-01 / DEPLOY-02 — PRD §10.0.2
##
## 构建要求：
##   - 前端构建产物在 ../../frontend/out/（Phase 5 完成后挂载或 COPY）
##   - nginx 配置在 ./nginx.conf
##
## 双模式构建：
##   1. 生产模式：COPY frontend/out → /usr/share/nginx/html（镜像自带）
##   2. 演示/开发模式：用 docker-compose volume mount 覆盖 /usr/share/nginx/html
##      （Phase 5 frontend build 完成后挂载 frontend/out 即可，无需重建镜像）

FROM nginx:1.27-alpine

## 1. 替换默认配置 — http 块 + server 块（PITFALLS #13/#20 已落地）
COPY nginx.conf /etc/nginx/nginx.conf

## 2. 预置 50x 错误页（轻量自定义）
RUN echo '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>服务暂不可用</title></head><body style="font-family:system-ui;text-align:center;padding:48px"><h1>服务暂不可用</h1><p>请稍后再试或联系运维</p></body></html>' \
    > /usr/share/nginx/html/50x.html

## 3. 占位 index.html — 当 frontend 未挂载时给出友好提示
##    （Phase 5 frontend build 产物挂载后会覆盖）
RUN echo '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>离职流程系统</title></head><body style="font-family:system-ui;padding:48px"><h1>离职流程系统 (offboarding-flow)</h1><p>前端尚未挂载。请构建 Phase 5 前端产物（pnpm build）后挂载 frontend/out → /usr/share/nginx/html</p><p>API 探活: <a href="/api/health">/api/health</a></p></body></html>' \
    > /usr/share/nginx/html/index.html

## 4. 健康检查（DOCKER HEALTHCHECK 由 compose 配，这里仅暴露端点）
EXPOSE 80

## 5. 默认启动 nginx（前台进程）
CMD ["nginx", "-g", "daemon off;"]
