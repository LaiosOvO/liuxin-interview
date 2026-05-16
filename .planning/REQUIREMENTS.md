# Requirements: offboarding-flow

**Defined:** 2026-05-16
**Core Value:** 让"流程状态机"端到端可见且可驱动 —— 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进到下一节点，直到申请人收到聚合所有节点执行内容的最终确认邮件。

## v1 Requirements

> 所有 REQ 都映射到 [ROADMAP.md](./ROADMAP.md) 的 6 个 phase，详见底部 Traceability。
> 验收标准：每个 REQ 在对应 phase verification 通过后即标 Complete。

### 流程引擎（Phase 1 + 2）

- [ ] **FLOW-01**: 离职流程 DAG 用 LangGraph StateGraph 定义，10 个节点 + 并行扇出扇入（apply → manager_review → hr_initial → [device_return ∥ access_revoke ∥ knowledge_handover ∥ finance_settle ∥ legal_sign] → hr_final → applicant_final_confirm → archive）
- [ ] **FLOW-02**: 节点函数自动同步写入业务表 `node_states` / `action_logs` / `flow_instances`，事务边界遵循 ARCHITECTURE §3 Pattern 1（业务事务 commit → 才 invoke LangGraph）
- [ ] **FLOW-03**: 进程崩溃后能从 `AsyncPostgresSaver` checkpoint 恢复执行；`docker restart` 流程进度无丢失
- [ ] **FLOW-04**: 每个人工节点统一为「自由文本 `result_text` + 三态决策 (advance / return / reject)」 — PRD §4.2 通用节点结构
- [ ] **FLOW-05**: 三态决策的退回路径按流程模板配置；拒绝在 manager_review / hr_initial / hr_final 等关键节点触发流程终止
- [ ] **FLOW-06**: 流程末尾的 `applicant_final_confirm` 节点自动聚合 `context.node_results[]` 渲染汇总邮件 — DF-02 ★★★★★

### 鉴权与深链（Phase 3）

- [ ] **AUTH-01**: 邮件 / IM 链接携带 JWT (含 `sub` / `role` / `flow_id` / `node_id` / `jti` / `exp`)，HS256 签名
- [ ] **AUTH-02**: 点击深链 → 前端调 `POST /api/auth/exchange` 用 token 换 HttpOnly Cookie；按 `role` 渲染对应视图
- [ ] **AUTH-03**: Token 一次性消费 — Redis `SET NX EX` 原子操作（防双击 race，PITFALLS #6）；节点状态变更时所有未消费 token 失效
- [ ] **AUTH-04**: Session 与 `(flow_id, node_id, sub)` 三元组绑定；跨节点 / 跨角色复用立即拒绝

### 通知（Phase 4，双通道）

- [ ] **NOTI-01**: 节点进入 `waiting_human` 时通过 `notification_outbox` 表 + APScheduler `outbox_drain` 异步发送邮件（QQ 邮箱 smtp.qq.com:465 SSL）— 不阻塞节点函数
- [ ] **NOTI-02**: 同时通过 Mattermost Bot Personal Access Token 推送 Interactive Message 卡片
- [ ] **NOTI-03**: 演示模式 (`APP_MODE=demo`) 下所有邮件路由到 `DEMO_INBOX=1624456575@qq.com`，主题前缀加角色标签 `[设备管理员·it.charlie]`，正文加横幅
- [ ] **NOTI-04**: 通知发送 / 失败 / 重试记录写入 `notifications` 表；outbox 表加 `UNIQUE(flow_id, node_state_id, channel)` 保证幂等
- [ ] **NOTI-05**: 节点超时 (>24h) 后台 APScheduler `timeout_scan` job 每分钟扫描自动重发提醒给 assignee + HR（Phase 6 落地）

### LLM 摘要（Phase 4，轻量增强）

- [ ] **LLM-01**: 接入 GLM API（智谱 AI coding plan），用 `openai` 包指向 `https://open.bigmodel.cn/api/paas/v4/`；`${GLM_API_KEY}` 环境变量注入
- [ ] **LLM-02**: 在 `applicant_final_confirm` 节点用 GLM 对各节点 `result_text` 做一段自然语言摘要，作为汇总邮件正文的开头总结段
- [ ] **LLM-03**: LLM 调用 `asyncio.timeout(8)` 超时；失败 / 超时不阻塞流程，降级为不带摘要的原始版本邮件

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
| FLOW-01 | Phase 1 + 2 | Pending |
| FLOW-02 | Phase 2 | Pending |
| FLOW-03 | Phase 1 | Pending |
| FLOW-04 | Phase 2 | Pending |
| FLOW-05 | Phase 2 | Pending |
| FLOW-06 | Phase 2 | Pending |
| AUTH-01 | Phase 3 | Pending |
| AUTH-02 | Phase 3 | Pending |
| AUTH-03 | Phase 3 | Pending |
| AUTH-04 | Phase 3 | Pending |
| NOTI-01 | Phase 4 | Pending |
| NOTI-02 | Phase 4 | Pending |
| NOTI-03 | Phase 4 | Pending |
| NOTI-04 | Phase 4 | Pending |
| NOTI-05 | Phase 6 | Pending |
| LLM-01 | Phase 4 | Pending |
| LLM-02 | Phase 4 | Pending |
| LLM-03 | Phase 4 | Pending |
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
- v1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0 ✓

---

*Requirements defined: 2026-05-16*
*Source: synthesized from .planning/PROJECT.md + .planning/research/SUMMARY.md + PRD.md v0.3*
*Last updated: 2026-05-16 after initial definition*
