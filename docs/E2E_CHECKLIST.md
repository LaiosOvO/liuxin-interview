# E2E 检查清单 — "Looks Done But Isn't" 18 项

> 演示前 / 大版本上线前必须逐项打勾。
>
> 设计动机：避免"代码看起来完成了，实际跑不通"的演示翻车场景。
>
> 来源：累积自 PITFALLS.md / SUMMARY.md / 演示场景实战教训
>
> 更新日期：2026-05-16（Phase 6 落地）

---

## 第一组：环境 / 凭证（演示翻车第一大类）

### 1. `.env` 已填真实凭证（不是 changeme_in_real_env）
```bash
grep -E "^(POSTGRES_PASSWORD|SMTP_PASSWORD|JWT_SECRET|MATTERMOST_BOT_TOKEN|GLM_API_KEY)" .env | grep changeme && echo "FAIL" || echo "OK"
```
- [ ] 通过：`OK`
- 失败：编辑 `.env` 填真实凭证

### 2. `APP_MODE=demo`（PITFALLS #10）
```bash
grep "^APP_MODE=" .env
```
- [ ] 通过：`APP_MODE=demo`
- 失败：演示模式邮件不会被覆写到 DEMO_INBOX，真实用户会收到混乱邮件

### 3. `DEEPLINK_BASE_URL` 不带 `:3000`（SUMMARY R1）
```bash
grep "^DEEPLINK_BASE_URL=" .env
```
- [ ] 通过：`DEEPLINK_BASE_URL=http://192.168.2.44`（无端口或显式 :80）
- 失败：深链跳 :3000 报"无法连接"

### 4. `.env` 已 `.gitignore`（PITFALLS #8）
```bash
git check-ignore .env && echo "OK" || echo "FAIL — .env 未被 gitignore"
```
- [ ] 通过：`OK`
- 失败：风险极高，所有凭证已可能进了 git history

### 5. `.env.example` 不含真值
```bash
grep -E "(qq_smtp_auth_code|@qq\.com|MII)" .env.example | grep -v "changeme" && echo "FAIL" || echo "OK"
```
- [ ] 通过：`OK`

---

## 第二组：服务健康 / 网络

### 6. 所有容器 healthy
```bash
docker compose ps
```
- [ ] postgres: `Up (healthy)`
- [ ] redis: `Up (healthy)`
- [ ] flow-api: `Up (healthy)`
- [ ] mock-archive-service: `Up (healthy)`
- [ ] nginx: `Up (healthy)`

### 7. flow-api 启动日志显示 `APP_MODE = DEMO`（PITFALLS #10）
```bash
docker compose logs flow-api | grep "APP_MODE ="
```
- [ ] 通过：`APP_MODE = DEMO`
- 失败：必须排查为何 prod 模式启动（演示会"漂"到真实邮箱）

### 8. nginx 反代 /api/ 正常（PITFALLS #20）
```bash
curl -i http://localhost/api/health | head -3
```
- [ ] 通过：`HTTP/1.1 200 OK` + `Content-Type: application/json`
- 失败：返回 `text/html` 说明 nginx `location /` 吞掉了 `/api/` — 检查 `^~` 前缀

### 9. nginx 静态 / 兜底正常
```bash
curl -i http://localhost/ | head -3
```
- [ ] 通过：`HTTP/1.1 200 OK` + `Content-Type: text/html`

### 10. nginx access log 不记录 query string（PITFALLS #13）
```bash
curl -s "http://localhost/api/health?token=secret123"
docker compose exec nginx tail -1 /var/log/nginx/access.log | grep -q "token=" && echo "FAIL — token 进了 log" || echo "OK"
```
- [ ] 通过：`OK`

---

## 第三组：数据库 / 迁移

### 11. alembic 已到最新版本
```bash
docker compose exec flow-api alembic current
```
- [ ] 通过：显示 head 版本号（如 `0002 (head)`）
- 失败：跑 `docker compose exec flow-api alembic upgrade head`

### 12. LangGraph checkpoint 表已 setup
```bash
docker compose exec offboarding-postgres psql -U flow -d offboarding \
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='langgraph';"
```
- [ ] 通过：含 `checkpoints` / `checkpoint_blobs` / `checkpoint_writes`
- 失败：跑 `docker compose exec flow-api python -m offboarding_flow.flow_engine.checkpointer --setup`

### 13. 业务表 schema 隔离正确（DEPLOY-01）
```bash
docker compose exec offboarding-postgres psql -U flow -d offboarding \
  -c "SELECT schemaname, COUNT(*) FROM pg_tables WHERE schemaname IN ('app', 'langgraph') GROUP BY schemaname;"
```
- [ ] 通过：app 8+ 表 / langgraph 3 表

---

## 第四组：演示数据 / Seed

### 14. 8 个测试账号已 seed 到本系统 + Mattermost
```bash
# 本系统 users 表
docker compose exec offboarding-postgres psql -U flow -d offboarding \
  -c "SELECT COUNT(*) FROM app.users;"
# Mattermost
curl -sf -H "Authorization: Bearer $MATTERMOST_BOT_TOKEN" \
  http://192.168.2.44:8065/api/v4/teams/name/laios/members | jq 'length'
```
- [ ] 通过：本系统 ≥ 8 / Mattermost ≥ 8
- 失败：跑 `docker compose exec flow-api python scripts/seed_demo_data.py`

### 15. 数据库已清空（演示前必检 — PITFALLS #28）
```bash
docker compose exec offboarding-postgres psql -U flow -d offboarding \
  -c "SELECT COUNT(*) FROM app.flow_instances;"
```
- [ ] 通过：`count = 0`（除非演示需要起 1 个流程做 fixture）
- 失败：跑 `./scripts/dev_reset.sh`

---

## 第五组：通知通道（演示翻车第二大类）

### 16. QQ SMTP 已预热（防限流，PITFALLS #14）
- [ ] 演示前 1 小时已手工触发 1 封测试邮件，QQ 邮箱已收到
- 失败：演示前再发一封 `@offboarding-bot start zhang.san` 测试

### 17. Mattermost @bot 在线 + AllowedUntrustedInternalConnections 已配（PITFALLS #7）
```bash
# Mattermost System Console → ServiceSettings 必须包含 192.168.2.44
# 否则 Interactive Message 按钮 callback 401
```
- [ ] 在 Mattermost 任意频道发 `@offboarding-bot help` 收到回复
- [ ] Mattermost System Console → ServiceSettings → AllowedUntrustedInternalConnections 含 `192.168.2.44`

---

## 第六组：端到端 smoke

### 18. smoke_test.sh 全部通过
```bash
BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh
```
- [ ] 通过：5 步全 OK，最终输出 `[smoke] ✓ Phase 1 冒烟通过`
- 失败：根据具体 step 错误排查（health / create flow / advance / get flow 任一）

---

## 紧急逃生通道

如果检查到 ≥ 3 项失败，且距离演示 < 30 分钟：

```bash
# 完整重置（5 分钟内恢复演示环境）
./scripts/dev_reset.sh
# 等 flow-api 健康后
docker compose exec flow-api python scripts/seed_demo_data.py
# 再重新走 18 项检查
```

如果上面仍失败，回滚到上一个 known-good commit：
```bash
git log --oneline -5
git reset --hard <known-good-commit>
./scripts/deploy_to_192_168_2_44.sh
```

---

## 演示中可能想问的问题速查

| 问题 | 速查 |
|---|---|
| flow_id 在哪看 | bot 启动回复卡片 / HR Dashboard |
| 当前节点状态 | `@offboarding-bot status <flow_id>` |
| 历史决策 | `app.action_logs` 表（HR Dashboard 可看） |
| 为何邮件去了 1624456575 | 演示模式覆写 `DEMO_INBOX_MAP`（PRD §9.1.3） |
| 流程为何卡住 | `@offboarding-bot report <flow_id>` 看 阻塞事项 |
| 超时如何触发 | `DEMO_TIMEOUT_OVERRIDE_HOURS=0.05` 等 3 分钟 |
| AutoNode 在哪 | `auto_archive_to_storage`（PRD §18） |
| 业务表 vs LangGraph 区别 | 双层状态分离（CLAUDE.md §3.3） |
