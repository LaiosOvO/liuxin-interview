# Requirements: offboarding-flow

**Defined:** 2026-05-16
**Core Value:** 让"流程状态机"端到端可见且可驱动 —— 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进到下一节点，直到申请人收到聚合所有节点执行内容的最终确认邮件。

## v1 Requirements

> 所有 REQ 都映射到 [ROADMAP.md](./ROADMAP.md) 的 6 个 phase，详见底部 Traceability。
> 验收标准：每个 REQ 在对应 phase verification 通过后即标 Complete。

### 流程引擎（Phase 1 + 2）

- [x] **FLOW-01**: 离职流程 DAG 用 LangGraph StateGraph 定义，10 个节点 + 并行扇出扇入（apply → manager_review → hr_initial → [device_return ∥ access_revoke ∥ knowledge_handover ∥ finance_settle ∥ legal_sign] → hr_final → applicant_final_confirm → archive）
- [x] **FLOW-02**: 节点函数自动同步写入业务表 `node_states` / `action_logs` / `flow_instances`，事务边界遵循 ARCHITECTURE §3 Pattern 1（业务事务 commit → 才 invoke LangGraph）
- [x] **FLOW-03**: 进程崩溃后能从 `AsyncPostgresSaver` checkpoint 恢复执行；`docker restart` 流程进度无丢失
- [x] **FLOW-04**: 每个人工节点统一为「自由文本 `result_text` + 三态决策 (advance / return / reject)」 — PRD §4.2 通用节点结构
- [x] **FLOW-05**: 三态决策的退回路径按流程模板配置；拒绝在 manager_review / hr_initial / hr_final 等关键节点触发流程终止
- [x] **FLOW-06**: 流程末尾的 `applicant_final_confirm` 节点自动聚合 `context.node_results[]` 渲染汇总邮件 — DF-02 ★★★★★

### 鉴权与深链（Phase 3）

- [x] **AUTH-01**: 邮件 / IM 链接携带 JWT (含 `sub` / `role` / `flow_id` / `node_id` / `jti` / `exp`)，HS256 签名
- [x] **AUTH-02**: 点击深链 → 前端调 `POST /api/auth/exchange` 用 token 换 HttpOnly Cookie；按 `role` 渲染对应视图
- [x] **AUTH-03**: Token 一次性消费 — Redis `SET NX EX` 原子操作（防双击 race，PITFALLS #6）；节点状态变更时所有未消费 token 失效
- [x] **AUTH-04**: Session 与 `(flow_id, node_id, sub)` 三元组绑定；跨节点 / 跨角色复用立即拒绝

### 通知（Phase 4，双通道）

- [ ] **NOTI-01**: 节点进入 `waiting_human` 时通过 `notification_outbox` 表 + APScheduler `outbox_drain` 异步发送邮件（QQ 邮箱 smtp.qq.com:465 SSL）— 不阻塞节点函数
- [ ] **NOTI-02**: 同时通过 Mattermost Bot Personal Access Token 推送 Interactive Message 卡片
- [ ] **NOTI-03**: 演示模式 (`APP_MODE=demo`) 下所有邮件路由到 `DEMO_INBOX=1624456575@qq.com`，主题前缀加角色标签 `[设备管理员·it.charlie]`，正文加横幅
- [ ] **NOTI-04**: 通知发送 / 失败 / 重试记录写入 `notifications` 表；outbox 表加 `UNIQUE(flow_id, node_state_id, channel)` 保证幂等
- [ ] **NOTI-05**: 节点超时 (>24h) 后台 APScheduler `timeout_scan` job 每分钟扫描自动重发提醒给 assignee + HR（Phase 6 落地）

### LLM / AI 能力（Phase 4，v0.4 大幅扩展）

- [x] **LLM-01**: 接入 GLM API — openai 包指向 `open.bigmodel.cn/api/paas/v4/` + `${GLM_API_KEY}` env 注入（Slice 4C / llm/glm_client.py）
- [x] **LLM-02**: applicant_final_confirm 节点 interrupt payload 加 `glm_summary` 字段 — Slice 4C；邮件正文渲染 Slice 4B 接入
- [x] **LLM-03**: LLM 调用 `asyncio.timeout(8)` + 失败 / 超时 / 空返回 → None 降级（Slice 4C / LLMService.complete）
- [x] **LLM-04**: AI 推理下一步建议 prompt `SUGGEST_NEXT_STEP_PROMPT` 就绪（Slice 4C / llm/prompts.py）；Dashboard / @bot suggest 调用方 Slice 4B 接入（PRD §15.1，评分点 #5）
- [x] **LLM-05**: AI 后台报告 prompt `GENERATE_REPORT_PROMPT` 就绪（Slice 4C / llm/prompts.py）；Dashboard / @bot report / 9am 定时调用方 Slice 4B/4D 接入（PRD §15.2，评分点 #7）
- [x] **LLM-06**: AI 边界声明 — `AI_HEADER 🤖` + `AI_DISCLAIMER` 锁定文案 + `wrap_ai_output` helper + `LLMService.complete` 自动包裹（Slice 4C / services/ai_disclaimer.py；PRD §15.3，评分点 #8）

### Mattermost @bot 入口（Phase 4，v0.4 新增）

- [ ] **BOT-01**: Mattermost Outgoing Webhook 配置 + `POST /api/mattermost/webhook` 端点接收 trigger word `@offboarding-bot`；Token 校验防伪造
- [ ] **BOT-02**: 命令解析器支持 `start` / `status` / `report` / `suggest` / `list` / `help` / `simulate-timeout` / `simulate-evidence-missing` 8 个命令；白名单 + 严格正则解析（PRD §16.2）
- [ ] **BOT-03**: Bot 通过 PAT 调 `POST /api/v4/posts` 在原频道回复；启动流程的回复一次性输出案件 ID / 8 角色清单 / 10 节点状态 / 当前进度 / 阻塞 / 是否需要真人 / 建议下一步（PRD §16.4，评分点 #1-9 一次回答）
- [ ] **BOT-04**: `start` 命令只允许 HR 角色或 Admin 触发；其他角色拒绝并提示

### 任务逾期与证据缺失（Phase 4 部分 + Phase 6 完善）

- [ ] **TIMEOUT-01**: 节点 SLA = `NODE_TIMEOUT_HOURS` env（默认 24h，演示用 `DEMO_TIMEOUT_OVERRIDE_HOURS=0.05`）；APScheduler `timeout_scan` 每分钟标记 `node_states.is_overdue=True`（PRD §17.1）
- [ ] **TIMEOUT-02**: **证据缺失检测** — `result_text` 长度 < 5 字符 或显式标记 `evidence_missing=True`；AI 报告中标 "⚠️ 节点 result_text 为空 / 内容过短，疑似证据缺失"（PRD §17.2，评分点 #6）
- [ ] **TIMEOUT-03**: Mattermost `@offboarding-bot simulate-timeout` / `simulate-evidence-missing` 命令支持立即触发，方便演示（PRD §17.1 + §17.2）
- [ ] **TIMEOUT-04**: HR Dashboard 节点旁显示 `⚠️ 证据待补充` / `⏰ 已超时` 标签

### 加分项：自动动作节点（Phase 4.5，v0.4 新增）

- [ ] **AUTO-01**: 新增 `AutoNode` 类型（不调用 `interrupt()` 直接执行）；演示节点 `auto_archive_to_storage` 插入 `applicant_final_confirm` 与 `archive` 之间（PRD §18.2，评分点 #9 加分项）
- [ ] **AUTO-02**: docker-compose 加一个 `mock-archive-service` 容器（FastAPI 10 行）接收 POST 写入 `/data/{flow_id}.json`；演示自动节点调用外部 HTTP API（PRD §18.2）
- [ ] **AUTO-03**: AutoNode 同样双写 `node_states`（status=done）+ `action_logs`（actor=`system:auto`）+ outbox 通知，证明架构对人机协同的对称支持

### 演示组织数据（Phase 4）

- [ ] **SEED-01**: `scripts/seed_demo_data.py` 通过 Mattermost REST API 创建 5 个 team (engineering / hr / it / finance / legal)；幂等（`ensure_team` GET-then-create）
- [ ] **SEED-02**: 创建 8 个测试账号（zhang.san / li.si / wang.wu / hr.alice / hr.bob / it.charlie / fin.david / legal.eve），写入 Mattermost Custom Attributes (`employee_id` / `department` / `role` / `manager_email`)
- [ ] **SEED-03**: Seed 完成后可一键发起一个 `standard_offboarding` 流程触发首封邮件；脚本启动校验 Mattermost `AllowedUntrustedInternalConnections` 配置

### 前端（Phase 5，多角色 + 一键登录）

- [ ] **WEB-01**: Next.js 15 静态导出 (`output: 'export'`) 由 nginx 直接 serve；Node 22 LTS + pnpm 11.1.1
- [ ] **WEB-02**: 一键登录入口 `/flow/handle?flow_id=xxx&node_id=yyy&token=zzz`（query string 格式，规避 Next.js 15 issue #79380）自动换 session，按 role 跳转视图
- [ ] **WEB-03**: 通用节点处理页 NodeForm（节点说明只读 + 详情文本输入必填 + 三态按钮颜色区分：继续=蓝 / 退回=黄 / 拒绝=红 + confirm dialog）
- [ ] **WEB-04**: 申请人最终确认页（在通用表单上额外展示节点结果时间线 + GLM 摘要段）
- [ ] **WEB-05**: HR Dashboard (`/hr/dashboard`) 总览所有流程；员工 `/my/flows` 查看自己进度；卡点筛选 + "重发通知"按钮

### 部署（Phase 1 骨架 + Phase 6 完善）

- [ ] **DEPLOY-01**: Docker Compose 编排 postgres / redis / flow-api / nginx；业务用 `app` schema + LangGraph 用 `langgraph` schema 双 schema 隔离
- [ ] **DEPLOY-02**: nginx 反代 `location ^~ /api/` → flow-api:8000；根路径 serve 前端静态产物 + `try_files /index.html` 兜底；`log_format` 不记录 query string 防 token 泄露
- [ ] **DEPLOY-03**: 一条命令 `docker compose up -d` 在 192.168.2.44 启动全套服务；启动 log 显式打印 `APP_MODE`
- [ ] **DEPLOY-04**: `.env.example` 模板覆盖所有必需配置（不含真值）；pre-commit gitleaks 钩子防密钥进 git
- [ ] **DEPLOY-05**: entrypoint.sh: `alembic upgrade head` → `await checkpointer.setup()` → `uvicorn`；alembic env.py `include_object` 过滤 `schema == 'langgraph'`

## v2 Requirements

> v1 后再做，不进 v1 roadmap

### 与外部业务系统真实集成

- **EXT-01**: 资产系统 API 对接（查设备清单 / 回写归还状态）
- **EXT-02**: AD/LDAP 触发权限回收
- **EXT-03**: 财务系统结算触发
- **EXT-04**: 每节点差异化表单 / 字段（payload.devices / payload.settlement 等结构化数据）

### 流程模板扩展

- **TMPL-01**: 多种离职流程模板（主动 / 被动 / 协议）
- **TMPL-02**: 节点附件上传
- **TMPL-03**: 节点子流程（执行 + 审核两层三态）

### 协作渠道扩展

- **CH-01**: 企业微信适配器
- **CH-02**: 飞书适配器
- **CH-03**: Mattermost Interactive Message callback 接收（v1 只做跳转 URL）

### 生产化

- **PROD-01**: SSO 集成（替代演示用 token 一键登录）
- **PROD-02**: HTTPS / TLS（替代内网 HTTP）
- **PROD-03**: RBAC 配置后台
- **PROD-04**: 移动端适配 / i18n / 多租户

## Out of Scope

| Feature | Reason |
|---------|--------|
| 通用 ChatBot 聊天界面 | 这是流程引擎不是 ChatBot — PROJECT.md Core Value 明确 |
| 流程模板可视化编排 (agent-builder) | v3 才考虑；v1/v2 流程模板硬编码 |
| 状态机 DAG 可视化（前端 React Flow） | 可作为加分项 v2 引入；v1 时间线足以演示 |
| BI 报表 / 流程 SLA 仪表盘 | 不在流程引擎核心能力范围 |
| Agent 自动节点（无人工介入节点）| 演示重心是人工流转，不需要 agent 自动决策 |
| GPL/AGPL 类许可证依赖 | 商业场景兼容性约束（所有依赖必须 MIT / Apache 2.0 / BSD）|

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FLOW-01 | Phase 1 + 2 | Complete |
| FLOW-02 | Phase 2 | Complete |
| FLOW-03 | Phase 1 | Complete |
| FLOW-04 | Phase 2 | Complete |
| FLOW-05 | Phase 2 | Complete |
| FLOW-06 | Phase 2 | Complete |
| AUTH-01 | Phase 3 | Complete |
| AUTH-02 | Phase 3 | Complete |
| AUTH-03 | Phase 3 | Complete |
| AUTH-04 | Phase 3 | Complete |
| NOTI-01 | Phase 4 | Pending |
| NOTI-02 | Phase 4 | Pending |
| NOTI-03 | Phase 4 | Pending |
| NOTI-04 | Phase 4 | Pending |
| NOTI-05 | Phase 6 | Pending |
| LLM-01 | Phase 4 / Slice 4C | Complete |
| LLM-02 | Phase 4 / Slice 4C | Complete |
| LLM-03 | Phase 4 / Slice 4C | Complete |
| LLM-04 | Phase 4 / Slice 4C | Complete |
| LLM-05 | Phase 4 / Slice 4C | Complete |
| LLM-06 | Phase 4 / Slice 4C | Complete |
| BOT-01 | Phase 4 | Pending |
| BOT-02 | Phase 4 | Pending |
| BOT-03 | Phase 4 | Pending |
| BOT-04 | Phase 4 | Pending |
| TIMEOUT-01 | Phase 6 | Pending |
| TIMEOUT-02 | Phase 4 | Pending |
| TIMEOUT-03 | Phase 4 | Pending |
| TIMEOUT-04 | Phase 5 | Pending |
| AUTO-01 | Phase 4.5 | Pending |
| AUTO-02 | Phase 4.5 | Pending |
| AUTO-03 | Phase 4.5 | Pending |
| SEED-01 | Phase 4 | Pending |
| SEED-02 | Phase 4 | Pending |
| SEED-03 | Phase 4 | Pending |
| WEB-01 | Phase 5 | Pending |
| WEB-02 | Phase 5 | Pending |
| WEB-03 | Phase 5 | Pending |
| WEB-04 | Phase 5 | Pending |
| WEB-05 | Phase 5 | Pending |
| DEPLOY-01 | Phase 1 + 6 | Pending |
| DEPLOY-02 | Phase 6 | Pending |
| DEPLOY-03 | Phase 6 | Pending |
| DEPLOY-04 | Phase 1 | Pending |
| DEPLOY-05 | Phase 1 + 6 | Pending |

**Coverage:**
- v1 requirements: 45 total（v0.4 新增 14 项：LLM-04/05/06 + BOT-01/02/03/04 + TIMEOUT-01/02/03/04 + AUTO-01/02/03）
- Mapped to phases: 45
- Unmapped: 0 ✓

**面试评分点对照**（PRD §15.0 同步）：
| # | 评分点 | 对应 REQ |
|---|--------|---------|
| 1 | 创建离职案件数据记录 | FLOW-01 |
| 2 | ≥ 3 角色 | SEED-02（实际 8 角色） |
| 3 | ≥ 5 任务步骤 | FLOW-01（实际 10 节点）|
| 4 | 每任务有状态 | FLOW-02 + DB schema |
| 5 | AI 输出下一步 | **LLM-04** |
| 6 | 任务逾期 / 证据缺失 | **TIMEOUT-01/02/03/04** |
| 7 | 输出后台报告 | **LLM-05 + BOT-03** |
| 8 | 标 AI 不能做必须人工 | **LLM-06** |
| 9 | 自动动作（加分）| **AUTO-01/02/03** |
| + | @bot 启动（核心入口）| **BOT-01/02/03/04** |

---

*Requirements defined: 2026-05-16*
*Source: synthesized from .planning/PROJECT.md + .planning/research/SUMMARY.md + PRD.md v0.3*
*Last updated: 2026-05-16 after initial definition*
