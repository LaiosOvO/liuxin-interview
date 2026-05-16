# 演示操作手册（DEMO RUNBOOK）— offboarding-flow

> 面试 demo 操作清单 + 评分点对照 + 故障排查
>
> 目标：30 分钟内完整演示离职流程的 9 个评分点（PRD §15.0）
>
> 更新日期：2026-05-16（Phase 6 落地）

---

## 1. 启动顺序（4 步）

### 1.1 部署前提

- 部署机：`192.168.2.44`（GigaByte laios）
- 已就绪：Mattermost (`:8065`) / MinIO (`:9000` + `:9001`)
- `.env` 已填真实凭证（QQ SMTP / GLM / JWT Secret / POSTGRES_PASSWORD / Mattermost Bot Token）

### 1.2 一键启动（推荐）

```bash
cd /path/to/offboarding-flow
./scripts/deploy_to_192_168_2_44.sh --seed
```

该脚本自动完成：
1. git pull 最新代码
2. docker compose run --rm frontend-build （构建 Next.js 静态产物）
3. docker compose up -d --build （启 postgres / redis / flow-api / mock-archive / nginx）
4. 等 flow-api 健康
5. alembic upgrade head
6. checkpointer.setup()
7. seed_demo_data.py（创建 8 个测试账号 + Mattermost team + user）
8. smoke test 探活

### 1.3 手工分步启动（备用 / 调试）

```bash
# Step 1: 起容器
docker compose --env-file .env up -d

# Step 2: 等 flow-api 健康
curl -sf http://localhost:8000/api/health

# Step 3: alembic migration（entrypoint.sh 已跑，仍 explicit 一次）
docker compose exec flow-api alembic upgrade head

# Step 4: LangGraph checkpoint setup
docker compose exec flow-api python -m offboarding_flow.flow_engine.checkpointer --setup

# Step 5: seed 测试数据
docker compose exec flow-api python scripts/seed_demo_data.py

# Step 6: 验证 nginx + smoke
curl -sf http://localhost/nginx-health
BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh
```

---

## 2. 8 个测试账号 + 3 个真实邮箱映射

> 来源：PRD §9.1.3（v0.3 修订）

| Username      | 姓名    | 角色           | 真实收件箱             |
| ------------- | ------- | -------------- | ---------------------- |
| `zhang.san`   | 张三    | 离职员工        | `1624456575@qq.com`    |
| `li.si`       | 李四    | 直属上级        | `1624456575@qq.com`    |
| `wang.wu`     | 王五    | 部门总监        | `1691517500@qq.com`    |
| `hr.alice`    | Alice   | HR 专员         | `1691517500@qq.com`    |
| `hr.bob`      | Bob     | HR 总监         | `1624456575@qq.com`    |
| `it.charlie`  | Charlie | IT 设备管理员   | `1691517500@qq.com`    |
| `fin.david`   | David   | 财务结算专员    | `jingzhi.lu@wayz.ai`   |
| `legal.eve`   | Eve     | 法务合规        | `jingzhi.lu@wayz.ai`   |

> Mattermost 上 email 用 `${realbox}+${username}@${domain}` 的 +alias 形式
> QQ / 企业邮箱默认把 `+alias` 投递到原邮箱，演示者真能收到邮件

**演示者建议**：
- 主屏开浏览器 + Mattermost
- 副屏开 QQ 邮箱（`1624456575@qq.com` 主流程链路）
- 三个邮箱同时打开是最佳体验，但单 QQ 邮箱够主流程

---

## 3. 演示话术（PRD §16.4 + §18.3）

### 3.1 开场（评分点 1-3，1 分钟）

> "这是 AI 驱动的离职流程执行系统。后端 LangGraph + FastAPI，前端 Next.js 静态导出。
> 流程模板硬编码 10 节点 DAG，涉及 8 个角色 — 远超评分要求的 3 角色 5 步骤。
> 我会从 Mattermost @bot 启动一个流程，演示完整的人机协作 + AI 边界。"

### 3.2 启动流程（评分点 1+7，2 分钟）

在 Mattermost `laios` team 的任意频道：
```
@offboarding-bot start zhang.san
```

Bot 在 30s 内回复 PRD §16.4 的卡片（评分点 1-9 一次性输出 — 案件 ID / 角色清单 / 任务步骤 / 当前进度 / 阻塞事项 / 是否需要真人 / 建议下一步）。

> "看，bot 一次性输出了评分点要求的全部信息。这是 LLM-04 的 AI 推理 + Mattermost 富文本卡片。"

### 3.3 演示 10 节点流转（评分点 2-4，5 分钟）

打开 QQ 邮箱 `1624456575@qq.com`，按时间顺序：

| 序号 | 邮件主题 | 操作 | 评分点 |
|---|---|---|---|
| 1 | `[员工·zhang.san] 离职申请填写待处理` | 点深链 → 填写表单 → 提交 → 自动以 zhang.san 登录 | 4 |
| 2 | `[上级·li.si] 离职申请审批待处理` | 点深链 → 选「继续」 + 填理由 → 提交 | 3 + 4 |
| 3 | `[HR 专员·hr.alice] HR 初审待处理` | 点深链 → 选「继续」 + 填初审意见 | 3 |
| 4-7 | 5 个并行节点的邮件（IT / 财务 / 法务 / 权限 / 知识交接）| 任意顺序点深链推进 | 3 + 4 |
| 8 | `[HR 总监·hr.bob] HR 终审待处理` | 点深链 → 选「继续」 + 总结 | 3 |
| 9 | `[员工·zhang.san] 离职最终确认（含 AI 摘要）` | 点深链 → 看时间线 + GLM 摘要 → 确认 | 5 + 7 |
| - | `auto_archive_to_storage`（无邮件，AutoNode 自动执行）| - | 9（加分项）|
| 10 | `archive` 完成通知 | 流程结束 | 1 + 4 |

### 3.4 演示 AI 能力（评分点 5+7+8，5 分钟）

#### 3.4.1 AI 建议下一步（LLM-04 / §15.1）
```
@offboarding-bot suggest <flow_id>
```

#### 3.4.2 AI 后台报告（LLM-05 / §15.2）
```
@offboarding-bot report <flow_id>
```

#### 3.4.3 AI 边界声明（§15.3 + §18.3）

> "注意：每个 AI 输出都带 disclaimer — `由 AI 生成，所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点`。
> 这是 §15.3 的 AI 边界声明 — 评分点 8。"
>
> "auto_archive_to_storage 是唯一的自动节点（AutoNode），调外部 HTTP API 归档。这是评分点 9 的加分项。
> 但 device_return / 法务签字这些节点故意保留为人工：法律责任 / 财务变动 / 法律行为 — AI 没权代签。
> 能不能自动做 ≠ 应不应该自动做。"

### 3.5 演示异常处理（评分点 6，3 分钟）

#### 3.5.1 超时模拟（NOTI-05 + TIMEOUT-01 / §17.1）

```bash
# 演示模式打开快速触发：
# .env 加 DEMO_TIMEOUT_OVERRIDE_HOURS=0.05
# docker compose restart flow-api
# 3 分钟后某个节点未推进 → timeout_scan worker 自动：
#   1. 标 node_states.is_overdue = True
#   2. 入队 outbox email 重发提醒（HR Dashboard 出现红色"超时"标签）
#   3. 收件箱再收到一封 [超时提醒] xxx 邮件
```

或在 Mattermost：
```
@offboarding-bot simulate-timeout <flow_id> <node_name>
```

#### 3.5.2 证据缺失模拟（TIMEOUT-02 / §17.2）

某节点提交时填写极短文本（如 "ok"），AI 报告会自动列出 `⚠️ XXX 节点 result_text 内容过短，疑似证据缺失`。

---

## 4. 评分点 9 项对照表（PRD §15.0）

| # | 评分点 | 演示动作 | 对应 PRD 位置 |
|---|---|---|---|
| 1 | 创建"离职案件"数据记录 | `@offboarding-bot start zhang.san` → 看 flow_id | §6.1 + §16.4 |
| 2 | 至少 3 个角色（员工 / HR / 运维） | 8 角色（含财务 / 法务 / 上级 / 总监 / IT）| §3 + §9.1 |
| 3 | 至少 5 个任务步骤 | 10 节点（含 5 并行）| §4.1 |
| 4 | 每个任务设置状态 | node_states 表 status enum 全程切换 | §6.1 |
| 5 | 模拟 AI 输出下一步 | `@offboarding-bot suggest` + 申请人最终确认页 GLM 摘要 | §15.1 + LLM-02 |
| 6 | 模拟任务逾期 / 证据缺失 | `DEMO_TIMEOUT_OVERRIDE_HOURS=0.05` + simulate-timeout 命令 | §17 |
| 7 | 输出后台报告 | `@offboarding-bot report` 看 markdown 结构化报告 | §15.2 + §16 |
| 8 | 标出 AI 不能做的动作 | 每个 AI 输出含 disclaimer + §15.3 清单 | §15.3 |
| 9 | （加分项）API/Webhook 自动节点 | auto_archive_to_storage 自动调 mock-archive-service | §18 |

---

## 5. 故障排查

### 5.1 已知问题（已修）

| 现象 | 解决 |
|---|---|
| `test_recover` 测试 hardcoded path 报错 | f3edb9a commit 已修 — 改用 `Path(__file__)` |
| 容器健康检查失败 | `docker compose logs flow-api` 查看 startup error |
| Mattermost AllowedUntrustedInternalConnections 未配 | Mattermost System Console → ServiceSettings 加 `192.168.2.44` |
| DEEPLINK 链接 :3000 报无法连接 | Phase 6 已修：`.env` 改 `DEEPLINK_BASE_URL=http://192.168.2.44`（无 :3000，SUMMARY R1） |

### 5.2 一般故障排查

#### "flow-api 启动失败"
```bash
docker compose logs --tail 100 flow-api
# 常见错误：
#   - "POSTGRES_PASSWORD 必须在 .env 设置" → 填 .env
#   - "checkpointer setup failed" → 检查 postgres 是否健康
```

#### "邮件没收到"
```bash
# 1. 看 outbox 表是否有 pending
docker compose exec offboarding-postgres psql -U flow -d offboarding \
  -c "SELECT id, channel, status, attempts, last_error FROM app.notification_outbox ORDER BY created_at DESC LIMIT 10;"

# 2. 看 worker 日志
docker compose logs flow-api 2>&1 | grep outbox_drain

# 3. QQ SMTP 限流？检查 last_error
# 解决：等几分钟再试；演示前先发一封测试邮件预热（PITFALLS #14）
```

#### "Mattermost @bot 不回复"
```bash
# 1. Outgoing Webhook 配置：Trigger Word = `@offboarding-bot`
#    Callback URL = http://192.168.2.44:8000/api/mattermost/webhook
# 2. AllowedUntrustedInternalConnections 必须含 192.168.2.44（PITFALLS #7）
# 3. 看 flow-api 日志：docker compose logs flow-api | grep webhook
```

#### "演示前要清空"
```bash
./scripts/dev_reset.sh   # 二次确认 + 自动备份 + 重启
# 然后
docker compose exec flow-api python scripts/seed_demo_data.py
```

#### "演示中卡住"
```bash
# 1. 查当前 active 流程
curl http://localhost/api/flows | jq '.data | length'

# 2. 看是否有 stuck 节点
@offboarding-bot list stuck

# 3. 看后台报告
@offboarding-bot report <flow_id>
```

### 5.3 紧急回滚

```bash
# 滚回上一个 git commit
git reset --hard HEAD~1
./scripts/deploy_to_192_168_2_44.sh --no-frontend
```

---

## 6. 演示前 30 分钟检查清单

请配合 `docs/E2E_CHECKLIST.md` 完整跑一遍（18 项检查），尤其确认：
- [ ] `.env` `APP_MODE=demo`（PITFALLS #10 — 防上线没切回 prod）
- [ ] QQ 邮箱已收到预热测试邮件（防 SMTP 限流，PITFALLS #14）
- [ ] Mattermost @offboarding-bot 在线
- [ ] HR Dashboard `http://192.168.2.44/` 能打开
- [ ] `curl http://192.168.2.44/api/health` 返回 200
- [ ] `./scripts/smoke_test.sh` 全部通过
- [ ] 数据库已用 `./scripts/dev_reset.sh && seed_demo_data.py` 清空 + 重 seed
