# Changelog

> 项目：offboarding-flow — AI 驱动的离职流程执行系统
> 格式：基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 1.1.0
> 版本：基于 [SemVer](https://semver.org/lang/zh-CN/)

所有 notable 变更将记录在本文件，按时间倒序排列。
每次实现新功能 / 修复 bug / 重构 / 调整文档结构都会追加到 `[Unreleased]` 节，正式发布版本时再切到对应版本号。

---

## [Unreleased]

### Phase 6 (2026-05-16) — 部署 + nginx 反代 + timeout_scan + 运维脚本 + 演示 runbook

**交付**：DEPLOY-01/02/03/04/05 + NOTI-05 + TIMEOUT-01 全部 Complete

#### Added — 部署基础设施（DEPLOY-01/02/03）
- `deploy/nginx/nginx.conf` — 反代配置：
  - `location ^~ /api/` → flow-api:8000（PITFALLS #20 优先级修正 — `^~` 防 `location /` SPA 兜底吞掉 API）
  - `location ^~ /ws/` 透传 WebSocket（v1 备用）
  - `location /` + `try_files $uri $uri.html $uri/index.html /index.html` 静态前端 + SPA 客户端路由兜底
  - `log_format access_no_query` 不记录 query string（PITFALLS #13 防 deeplink token 进日志）
  - upstream keepalive 16 + proxy_buffering off（流式响应实时）
- `deploy/nginx/Dockerfile` — nginx:1.27-alpine + 占位 index.html + 50x 错误页；Phase 5 frontend/out 挂载后无需重建
- `docker-compose.yml` 增量 add：
  - `nginx` 服务（depends_on flow-api healthy + healthcheck /nginx-health + restart unless-stopped）
  - `frontend-build` 一次性 build 容器（profiles: build；docker compose --profile build run frontend-build）
  - flow-api env 新增 `NODE_TIMEOUT_HOURS` + `DEMO_TIMEOUT_OVERRIDE_HOURS`
  - DEEPLINK_BASE_URL 默认改 `http://192.168.2.44`（SUMMARY R1 — 无 :3000）

#### Added — 超时扫描（NOTI-05 + TIMEOUT-01）
- `backend/src/offboarding_flow/workers/timeout_scan.py`（PRD §17.1）：
  - `compute_sla_hours(settings)` 优先级：demo 模式 + DEMO_TIMEOUT_OVERRIDE_HOURS 已设 → 用 override；否则 NODE_TIMEOUT_HOURS（24h 默认）
  - `find_overdue_nodes(session, settings)` SELECT `status='waiting_human' AND entered_at < threshold`
  - `enqueue_timeout_reminders(session, nodes, settings)`：
    1. _mark_overdue 标 is_overdue=True（幂等）
    2. _has_been_reminded 防重发（action_log action='timeout_remind_sent'）
    3. 查 user.email + enqueue outbox email（recipient=assignee；演示模式 envelope 层覆写到 DEMO_INBOX）
    4. node_state_id=None 入队避开 UNIQUE 与首次通知冲突
    5. 写 action_log 幂等标识 + 唤醒 outbox drain
  - `TimeoutScanWorker` 60s 心跳 + 优雅 stop（与 OutboxDrainWorker 同 pattern）
- `backend/src/offboarding_flow/config.py` 新增 3 个字段：`node_timeout_hours` (24.0) / `demo_timeout_override_hours` (None) / `timeout_scan_interval_seconds` (60.0)
- `backend/src/offboarding_flow/main.py` lifespan — 与 OutboxDrainWorker 并列起 task；顺序 start outbox → start timeout / stop timeout → stop outbox（让最后一批 outbox 仍能 drain）

#### Added — 运维脚本（DEPLOY-03/04）
- `scripts/dev_reset.sh` — PITFALLS #9 双重保护：交互确认（RESET/yes） + 自动 pg_dump.gz 备份到 `/tmp/offboarding-pgdump-YYYYMMDD-HHMMSS.sql.gz` + docker compose down -v 才执行
- `scripts/cleanup_old_checkpoints.py` — PITFALLS #25：按业务表 status IN ('completed','rejected') 找已归档流程（updated_at < N 天）；级联删 langgraph.checkpoints/blobs/writes；--dry-run + --days N + --dsn 参数
- `scripts/deploy_to_192_168_2_44.sh` — 一键部署：git pull → frontend-build → docker compose up -d --build → 等 health → alembic → checkpointer.setup → 可选 seed → smoke + nginx 探活；--no-frontend / --no-pull / --seed flag

#### Added — 演示文档（DEMO 演示翻车防护）
- `docs/DEMO_RUNBOOK.md`（PRD §15.0 评分点 1-9 对照表 + §16.4 启动话术 + §18.3 AutoNode 话术）：
  - 启动顺序 4 步 + 手工分步备用
  - 8 测试账号 → 3 真实邮箱映射表（PRD §9.1.3）
  - 10 节点演示动作清单（按时间序）
  - 5 大故障排查清单（已知问题 + 邮件没收到 + bot 不回复 + 演示前清空 + 紧急回滚）
  - 演示前 30 分钟检查清单引用 E2E_CHECKLIST
- `docs/E2E_CHECKLIST.md`：18 项"Looks Done But Isn't"检查（环境凭证 5 项 + 服务网络 5 项 + 数据库 3 项 + Seed 2 项 + 通知 2 项 + smoke 1 项 + 紧急逃生通道）

#### Changed — .env.example
- DEEPLINK_BASE_URL 默认值 `http://192.168.2.44`（删 :3000，SUMMARY R1 + PITFALLS #21）
- 新增 Phase 6 节：`NODE_TIMEOUT_HOURS=24` / `DEMO_TIMEOUT_OVERRIDE_HOURS=` (空) / `TIMEOUT_SCAN_INTERVAL_SECONDS=60`
- 新增演示模式邮箱映射段：`DEMO_INBOX_MAP=` (空，留待 a99b1cb commit 已有 DEMO_INBOX_MAP_DEFAULT 兜底)

#### Tests
- `backend/tests/test_timeout_scan.py` — 17 单元 PASS + 1 integration skip：
  - `TestComputeSlaHours` × 5：默认 24h / demo override 优先 / prod 忽略 override / 自定义 / 0 边界
  - `TestComputeThreshold` × 3：24h 计算 / demo 3 分钟 / now() 默认
  - `TestFindOverdueNodes` × 2：空 / 返回超时节点
  - `TestEnqueueTimeoutReminders` × 3：超时入队 + is_overdue + action_log；已发过 skip；payload schema 对齐 outbox_drain
  - `TestScanOnce` × 2：无超时 / 端到端入队
  - `TestTimeoutScanWorker` × 2：stop 优雅退出（< 1s） / _safe_scan 吞异常
  - 集成测试 skip 占位（留待 testcontainers）

#### REQ Status
- NOTI-05 → Complete（每 60s timeout_scan + 重发提醒）
- TIMEOUT-01 → Complete（NODE_TIMEOUT_HOURS env + DEMO_TIMEOUT_OVERRIDE_HOURS + 标 is_overdue）
- DEPLOY-01 / DEPLOY-02 / DEPLOY-03 / DEPLOY-04 / DEPLOY-05 → Complete

#### Deferred / 未在本 phase 范围
- 前端 frontend/out 构建产物（Phase 5 在并行 worktree）
- TIMEOUT-03 simulate-timeout / simulate-evidence-missing 命令 → Phase 4 BOT 已部分实现（待与 timeout_scan 集成 follow-up）
- TIMEOUT-04 HR Dashboard 标签 → Phase 5（前端）

---

### Phase 4 Slice 4D (2026-05-16) — outbox drain（in-process 事件驱动）+ 证据缺失检测 + Seed + alembic 0002

**用户明确两条**：
1. "不要轮询，改事件驱动"
2. "事件驱动是机制上事件驱动不是数据库的事件驱动" — 用 `asyncio.Event` in-process，**不**用 DB LISTEN/NOTIFY 触发器
3. "如果是消息中枢的话就是用事件来中转直接" — outbox 作为消息中枢，事件作为唤醒中转
4. "记得加 debug 日志后期 debug 需要" — drain 链路加 DEBUG 级别 trace（cycle 计数 / 唤醒源 / 单行 dispatch 上下文）

#### Added
- `backend/migrations/versions/0002_evidence_missing_and_outbox_notify.py`：
  - `node_states.evidence_missing` Boolean 列（TIMEOUT-02 评分点 #6）— 默认 false
  - **注**：去掉 DB 触发器（最初实现，后按用户澄清改为 in-process 事件机制）
- `backend/src/offboarding_flow/workers/` 新子包:
  - `outbox_drain.py`：
    - 模块级 `asyncio.Event` + `signal_outbox_pending()` API — 业务侧 commit 后调一次即唤醒 worker（in-process 机制层事件，**不**走 DB 触发器）
    - `OutboxDrainWorker` 主循环：`asyncio.wait({signal_event, stop_event}, timeout=HEARTBEAT_SECONDS)` 三方择优唤醒
    - `drain_once` 按 channel 分发到 EmailSender / MattermostSender；指数退避（60/120/240s）；attempts≥3 切 status=failed
    - 优雅 stop（lifespan shutdown 5s wait_for）
    - 全链路 DEBUG 日志：signal 调用 / cycle 计数 / 唤醒源（signal 或 heartbeat）/ 每行 dispatch begin
  - `evidence_missing_detector.py`：`detect_evidence_missing(node)` — 显式标记优先 + result_text<5 字符兜底
- `services/flow_service.py`：create_flow commit 后调 `signal_outbox_pending()` 闭环事件机制（导入失败容错 DEBUG）
- `main.py` lifespan：起 OutboxDrainWorker asyncio task + shutdown 优雅 stop
- `state_store/models.py` NodeState 加 `evidence_missing` 列
- `scripts/seed_demo_data.py` 完整重写（215 行）— mattermostautodriver + 5 team + 8 user + Custom Attributes + AllowedUntrustedInternalConnections 校验 + `--create-flow` 触发首封邮件
- `backend/pyproject.toml` deps：mattermostautodriver>=2.0,<3
- 测试：unit 22 PASS（evidence_missing_detector 11 + outbox_drain 11，含 HEARTBEAT_SECONDS≥30s 防退化为轮询的保护断言）

#### Architecture Decision — 机制层事件驱动（最终定型）
- 决策 1：不轮询 — 移除 APScheduler 周期任务想法
- 决策 2：**机制层 in-process** 事件，不用 DB LISTEN/NOTIFY（用户明确："事件驱动是机制上事件驱动不是数据库的事件驱动"）
- 实现：`asyncio.Event` 模块级单例 + `signal_outbox_pending()` API
- 触发链：业务 enqueue → commit → signal_outbox_pending → worker wake → drain_once
- 60s 心跳兜底处理 signal 漏调用 / worker 重启窗口
- 整个系统的事件链：用户点邮件 → token exchange → graph.invoke → 下一节点 enter waiting_human → enqueue + signal → outbox worker dispatch → 用户下一封邮件
- 实时性 < 1ms 应用层延迟（vs 原 10s 轮询）

#### REQ Status
- NOTI-01 → Complete（outbox enqueue + 事件驱动 drain + 3 次重试）
- TIMEOUT-02 → Complete（evidence_missing 列 + 检测 helper）
- SEED-01 / SEED-02 / SEED-03 → Complete

#### Deferred to Phase 6
- TIMEOUT-01 完整 SLA 扫描 → Phase 6（NODE_TIMEOUT_HOURS env + 每分钟 timeout_scan job）
- TIMEOUT-04 HR Dashboard 标签 → Phase 5（前端）

#### 修 pre-existing test bug
- `test_recover_main_cli_help_runnable` 硬编码 phase-2-offboarding worktree 路径 → 改 `Path(__file__).resolve().parents[1]` 自动定位

---

### Phase 4.5 Complete (2026-05-16) — AutoNode + mock-archive-service 演示加分项

**交付**：Phase 4.5 加分项落地（PRD §18 / REQ AUTO-01/02/03 全部 Complete）— 与 Phase 4 在独立 worktree 并行开发

#### Added
- `services/auto_node_service.py` — AutoNode 双写 helper（与 NodeService.submit_action 架构对称）：upsert node_states (status=done) + INSERT action_log (action=SYSTEM, actor=system:auto) + append flow.context.node_results；SUCCESS / FAILED 两条独立 path
- `flow_engine/nodes/auto_archive_to_storage.py` — 演示自动节点：httpx async POST mock-archive-service + tenacity 3 次指数退避重试 + 失败 raise ArchiveServiceError
- `mock-archive-service/` — FastAPI 极简归档服务（30 行 main.py + Dockerfile + requirements.txt + .dockerignore）：接收 POST /archive 写入 `/data/archive/{flow_id}.json`
- graph.py 拓扑插入：applicant_final_confirm advance → auto_archive_to_storage → archive（保持 return → hr_final 不变）
- 配置项 `archive_service_url` / `archive_service_timeout_seconds` / `archive_service_max_retries`（Pydantic Settings）
- 测试三层（CLAUDE.md §2）：
  - 单元 9 用例：AutoNodeService 双写 3 测试 + 节点函数 mock httpx 6 测试（含 tenacity 重试 + 5xx 边界 + flow_id 校验）
  - 集成 2 用例：真 mock-archive-service subprocess（随机端口） + mock DB session — 成功路径 + 节点函数端到端
  - 图结构 2 新增：auto_archive→archive 边 + applicant→archive 直接边移除校验

#### Changed
- `flow_engine/routes.py`：`route_after_applicant` advance 返回从 `ARCHIVE` 改为 `AUTO_ARCHIVE_TO_STORAGE`
- `flow_engine/graph.py`：节点数 10 → 11（拓扑文档块更新；compile 日志改 11 nodes）
- `flow_engine/nodes/__init__.py`：export AUTO_ARCHIVE_TO_STORAGE_NODE_* 常量 + `auto_archive_to_storage_node`
- `services/__init__.py`：export `AutoNodeService`
- `tests/test_graph_topology.py`：节点数预期从 11 升到 12（含 auto_archive）；新增 auto_archive→archive 边校验 + applicant→archive 直接边移除校验
- `tests/test_routes.py`：route_after_applicant advance / reject / None 路径全部断言改为 AUTO_ARCHIVE_TO_STORAGE

#### Infrastructure
- `docker-compose.yml`：追加 mock-archive-service service（端口 5050:5000，volume `/data/offboarding/archive`，healthcheck）；flow-api `depends_on` 含 mock-archive-service service_healthy；flow-api environment 含 ARCHIVE_SERVICE_URL
- `.env.example`：追加 Phase 4.5 段 3 个配置项占位
- 与 Phase 4 worktree 并行无冲突：本 worktree 不动 notification_outbox / scheduler / Mattermost / GLM 模块

#### REQ Status
- AUTO-01 / AUTO-02 / AUTO-03 全部 Complete

#### Architectural Insight（PRD §18.3 演示话术）
> 「这里 auto_archive_to_storage 节点状态直接是 done，actor=system:auto，证明本架构同时支持人机交互节点（三态决策）和自动节点（API/Webhook）。未来要接 RPA 或者业务系统真实 API，模式完全一致：节点函数里调外部 API，双写业务表。但是 — 注意我故意没有把 device_return 等节点改成自动节点，因为：设备归还涉及法律责任必须人工签字；财务结算金额变动需要财务 review；法务签字本质是法律行为，AI / 自动节点无权代签。这就回到 §15.3 的 AI 边界声明：能不能自动做 ≠ 应不应该自动做。」

#### Deferred to Future Phase
- notification_outbox 集成（AutoNode 完成时也 enqueue 一条「自动执行」通知）→ Phase 4 落地 outbox 后再追加 stub 调用
- 接真实业务系统 API（device_return 写回 / AD 权限回收 / 财务系统结算触发）→ v2（EXT-01/02/03）
- 接 RPA 框架（UiPath / Browser-use）→ v3（PRD §18.4）
- mock-archive-service 鉴权 / TLS / volume 持久化策略 → v2（生产化）

---

### Phase 4 / Slice 4C — LLM + Prompt 模板 + AI Disclaimer + applicant_summary (2026-05-16)

**交付**：Slice 4C 落地全部 LLM-01..06，AI 能力用 prompt 模板封装不为每能力单独写 class
（用户 memory feedback `feedback_capability_design`）。Slice 4B handler 直接 await
`applicant_summary` / `LLMService.complete(SUGGEST_NEXT_STEP_PROMPT / GENERATE_REPORT_PROMPT)`
即可接入 bot/邮件。

#### Added
- `backend/src/offboarding_flow/llm/`（新子包）
  - `glm_client.py`：AsyncOpenAI 单例 base_url=`open.bigmodel.cn/api/paas/v4/`（LLM-01 + STACK.md §4.6）
  - `prompts.py`：3 个 `(system, user_template)` 模板 + `render_prompt(template, **ctx)`
    - `SUMMARIZE_FOR_APPLICANT_PROMPT`（LLM-02 / PRD §4.5.2 ≤ 100 字一句话）
    - `SUGGEST_NEXT_STEP_PROMPT`（LLM-04 / PRD §15.1 ≤ 200 字四要素）
    - `GENERATE_REPORT_PROMPT`（LLM-05 / PRD §15.2 markdown 4 段）
- `services/llm_service.py`：`LLMService.complete(template, context, timeout)`
  - `asyncio.timeout(8)` 硬上限（PITFALLS #22 + LLM-03）
  - 任何异常 / 超时 / 空返回 → `None`（调用方走规则模板兜底，绝不抛出）
  - 自动 append `wrap_ai_output`（LLM-06）
  - lazy `_get_client()` — 测试可注入 mock client 不依赖真 GLM
- `services/ai_disclaimer.py`：`AI_HEADER 🤖` + `AI_DISCLAIMER` 锁定文案
  + `wrap_ai_output(text, with_header)` — markdown 报告可关 header 保留标题层级
- `services/applicant_summary_service.py`：`applicant_summary(node_results, llm_service)`
  - 空 / 序列化失败 / 非 dict 元素 → None（防御性）
  - 注入 LLMService 友好（测试 mock）
- `flow_engine/nodes/applicant_final_confirm.py` 扩展
  - `_safe_glm_summary(timeline)` helper — 任何异常吞掉返回 None（节点函数硬不阻塞）
  - interrupt payload 新增 `glm_summary` 字段（None 时调用方走原始 timeline 降级邮件）
  - 既有 7 个 applicant 测试零回归

#### Changed
- `config.py`: 新增 `glm_api_key` / `glm_base_url` / `glm_model` / `glm_timeout_seconds`
- `services/__init__.py`: export LLMService / AI_DISCLAIMER / AI_HEADER / wrap_ai_output
- `pyproject.toml`: 加 `openai>=1.40,<2` dep（STACK.md §4.6）
- `.env.example`: 补 `GLM_BASE_URL` / `GLM_MODEL` / `GLM_TIMEOUT_SECONDS` 占位

#### Tests (41 新增全 PASS + 7 既有 applicant 零回归)
- Unit:
  - `test_ai_disclaimer.py` ×6 — header / disclaimer / 空输入 / markdown 模式 / 文案锁定
  - `test_llm_prompts.py` ×9 — 3 模板渲染 + system 段 PRD 约束断言 + 缺占位符 KeyError
  - `test_llm_service.py` ×9 — 正常 / 超时 / 异常 / 空 / disclaimer 开关 / model+messages
  - `test_applicant_summary_service.py` ×8 — 空 / 正常 / mock 验证 prompt 与 context / 防御性序列化
  - `test_applicant_final_confirm_glm.py` ×4 — interrupt payload glm_summary 字段三态
- Integration: `tests/integration/test_llm_real_glm.py` — 真 GLM API 默认 skip
  （仅当 `GLM_API_KEY` 非占位符时启用）
- E2E: `tests/e2e/test_applicant_summary_e2e.py` — Slice 4D 集成时填充（当前占位）

#### REQ Status
- LLM-01 / LLM-02 / LLM-03 / LLM-04 / LLM-05 / LLM-06 全部 Complete

#### Deferred to Slice 4B / 4D
- bot_service `report` / `suggest` 命令实际 `await llm_service.complete(...)` 接入
- 申请人确认邮件正文渲染 `glm_summary` 段 + 降级到原始 timeline
- Phase 4 完整 E2E（真起流程 → 申请人确认 → 验证邮件有摘要）

---

### Phase 4 Slice 4A (2026-05-16) — notifications/ 子包 + 邮件 outbox 基础设施

**交付**：REQ-NOTI-01（部分）+ NOTI-03 + NOTI-04 — outbox 模式入队、SMTP 发送层、演示模式信封覆写、HTML 模板

#### Added
- `backend/src/offboarding_flow/notifications/` 子包：
  - `outbox_repository.py` — OutboxRepository (enqueue ON CONFLICT 幂等 / list_pending FOR UPDATE SKIP LOCKED / mark_success / mark_failed 退避)
  - `email_sender.py` — aiosmtplib + QQ smtp.qq.com:465 + use_tls=True + EmailMessage 自动 RFC 2047 编码中文 subject（PITFALLS #15）
  - `email_envelope.py` — EmailEnvelope dataclass + build_envelope() 单点收口 demo/prod 差异：`delivery_to` 覆写 / 主题加 `[角色中文·username]` 前缀 / HTML 正文加横幅（PITFALLS #10 + PRD §7.4.1）
  - `templates/node_waiting_email.html` — jinja2 table-based 中文邮件模板，含立即处理按钮 + 深链 fallback（与 Phase 3 build_deep_link 集成）
- `services/notification_service.py` — NotificationService 业务层 + render_node_waiting_email 纯函数渲染
- `api/deps.py` — get_outbox_repo / get_notification_service DI 注入 + FlowService 接 notification_service
- `services/flow_service.py` — create_flow 在 manager_review 入 WAITING_HUMAN 后事务内 enqueue 邮件 outbox（失败仅 log 不阻断）
- `config.py` 扩展 SMTP_HOST / SMTP_PORT / SMTP_USE_SSL / SMTP_USER / SMTP_PASSWORD / SMTP_FROM_NAME / DEMO_INBOX
- prod 模式启动新增 SMTP_PASSWORD 占位校验（继 JWT_SECRET 校验风格）
- pyproject.toml deps: aiosmtplib>=3,<5 + jinja2>=3.1,<4；pytest markers 注册 `unit`

#### Tests
- 单元 19 PASS：
  - test_email_envelope.py (7) — demo 覆写 / 角色映射 / 横幅 / prod passthrough / 未知 role fallback / ROLE_CN_MAP 完整性
  - test_email_sender.py (7) — RFC 2047 编码 + round-trip 解码 / multipart alternative / To header / 非法 SMTP_USER 兜底 / mock smtp 成功失败路径
  - test_notification_service.py (5) — HTML 含深链 + 节点元数据 + 中文 / text 纯文本 fallback / jinja autoescape XSS 防护 / enqueue payload 完整性 / 幂等冲突 None 返回
- 集成 4（OutboxRepository CRUD + 幂等 + 退避，DB 不可达自动 skip）+ 1（MailHog 真发邮件 + API 验证主题编码，端口不可达自动 skip）— mailpit 启动方式见 test_email_sender_integration.py docstring
- 全套 178 passed / 26 skipped（与 Phase 3 完成时一致 + 19 新增）

#### Out of scope (defer to later Slice)
- Slice 4B: Mattermost outbox + Interactive Message 卡片
- Slice 4D: APScheduler outbox_drain job + notifications 表写入 + tenacity 重试 + 限流 Semaphore（PITFALLS #14）
- Phase 5: users 表接 assignee 真实邮箱（当前 flow_service 用 `{assignee}@demo.local` 占位）

#### REQ-ID 状态
- NOTI-01: Partial（outbox + EmailSender 完成，drain 待 4D）
- NOTI-03: Complete
- NOTI-04: Complete（outbox 幂等；notifications 表写入待 4D）

---
### Phase 4 Slice 4B — Mattermost @bot 入口 + 出站发送器（2026-05-16）

**交付**：Phase 4 Slice 4B 完整落地（NOTI-02 + BOT-01..04）— Mattermost 出站 +
Outgoing Webhook 入站 + 8 命令 handler + role 校验。

#### Added
- `notifications/` 子包初版：
  - `mattermost_sender.py` — httpx async Bot PAT 调 `POST /api/v4/posts` +
    Interactive Message attachments + `build_action_attachment` helper；
    `MattermostMessage` immutable DTO；4xx/5xx/网络错误统一抛 `MattermostSendError`
- `services/bot_command_parser.py` — 严格正则白名单解析 8 命令（PRD §16.5 安全）：
  username `[a-zA-Z][a-zA-Z0-9._-]{0,63}`，flow_id 8 位短 ID 或完整 UUID，
  node_name 小写字母 + 数字 + 下划线（PRD §16.5 不接受 eval）
- `services/bot_service.py` — 8 命令 handler 分发：
  - `start <username>` 严格按 PRD §16.4 样例 9 段格式（案件 ID / 8 角色 / 11 节点 /
    进度 / 阻塞 / 是否需人 / 建议 / AI disclaimer）；调用 FlowService.create_flow 复用 Phase 2 双写
  - `status <flow_id>` 结构化进度卡片
  - `list [active|completed|stuck]` — 列流程，stuck 过滤 `is_overdue=True`
  - `help` — 列 8 命令清单 + disclaimer
  - `simulate-timeout` — `UPDATE node_states SET is_overdue=True`（demo 用）
  - `simulate-evidence-missing` — append `flow_instances.context.evidence_missing_nodes`
  - `report` / `suggest` — Slice 4C 接 LLM；当前返回 stub "AI 报告功能开发中"
  - BOT-04 role 校验：仅 `hr` / `hr_admin` / `admin` 可触发 start
- `api/mattermost_webhook.py` — `POST /api/mattermost/webhook` 端点：
  - Outgoing Webhook form-data（token / text / user_name / channel_id 等）
  - Token 校验防伪造（不一致 401，PRD §16.5）
  - 业务异常友好回复（不泄漏内部细节）
  - 返回 Mattermost-compatible JSON `{"text": "...", "response_type": "in_channel"}`
- `config.py` — 新增 Settings 字段：mattermost_url / team / bot_username /
  bot_user_id / bot_token / **outgoing_webhook_token** / http_timeout
- `.env.example` — 补 `MATTERMOST_OUTGOING_WEBHOOK_TOKEN` /
  `MATTERMOST_HTTP_TIMEOUT` 占位（凭证仍占位 `changeme_in_real_env`）

#### Tests
- **单元（71 用例全 PASS）**：
  - `test_bot_command_parser.py` — 38 用例覆盖 8 命令 + 参数 / 正则 / mention 剥离 /
    大小写 / 边界
  - `test_bot_service.py` — 12 用例覆盖 start 9 段格式 + BOT-04 role 校验 + 8 命令
    dispatch 路由 + stub 标识 + AI disclaimer
  - `test_mattermost_sender.py` — 11 用例（含端到端契约测试模拟 MM server）覆盖
    URL / Bearer header / props.attachments / 4xx / 5xx / 网络错误 / context manager
- **集成（5 用例 — 需 `TEST_DATABASE_URL`，默认 skip）**：
  - `tests/integration/test_mattermost_webhook.py` — 真 PG + FastAPI ASGI 拦截：
    token 校验 / help / 未知命令 / BOT-04 拒绝 / HR user start 成功且回复含 9 段
- **跳过**：真 Mattermost 容器测试 — `docker compose up mattermost -d` 后导出
  `MATTERMOST_BOT_TOKEN_REAL` 跑 e2e 标记

#### Security
- Outgoing Webhook token 校验（PRD §16.5 防伪造）
- 命令解析全部走严格白名单正则（不 eval / 不动态执行）
- start 命令 role 校验白名单：`hr` / `hr_admin` / `admin`（业务表 users.role）
- 所有 AI 输出（help / start / report / suggest stub）必带 disclaimer
  "AI 不会自动操作任何节点；所有决策必须人工确认"（CLAUDE.md §5）
- Bot Token / Webhook Token 通过 `.env` 注入；`.env.example` 仅占位（CLAUDE.md §3.5）

#### REQ Status
- NOTI-02 / BOT-01 / BOT-02 / BOT-03 / BOT-04 全部 Complete (Slice 4B)

#### Deferred
- LLM 接入 report / suggest → Slice 4C
- mattermost_sender 接入 outbox_drain（异步重试 / 幂等）→ Slice 4D
- Mattermost AllowedUntrustedInternalConnections seed 健康检查（PITFALLS #7）→ Phase 6
- 真 Mattermost 容器 e2e 测试 → 部署后补

### Phase 3 Complete (2026-05-16) — merged via worktree-phase-3-auth

**交付**：Phase 3 鉴权 + 深链 JWT 一键登录 + jti 一次性消费完整落地（AUTH-01..04 全部 Complete）

#### Added
- auth/ 子包 10 文件：jwt_service / deep_link / jti_service / cookie / role_router / session_service / deps / errors / schemas / redis_client
- `POST /api/auth/exchange` — PRD §6.2.2 锁定 7 步校验链
- `POST /api/auth/logout` — 清 cookie
- 节点状态变更后 token 失效 hook（NodeService.submit_action 在 session.commit 后调 jti_service.invalidate_node_tokens；失败仅 log warning 不阻断主链路）
- get_current_user + require_role(*roles) FastAPI Depends 体系
- 全局 AuthError handler — 统一 401 envelope（detail='鉴权失败' 不泄露细节，server log 写 reason）
- HttpOnly + SameSite=Lax cookie（PITFALLS #12 — 不能 Strict 否则邮件跨站跳失效）
- secure=(APP_MODE=='prod' and HTTPS_ENABLED) — 内网 HTTP 不开 Secure
- 深链 URL 方案 A query string 格式（PRD §6.2 + SUMMARY R2 — 规避 Next.js 15 issue #79380）
- Redis SET NX EX 原子操作消费 jti（PITFALLS #6 防双击 race）
- node:jti:{node_id} SET 维护未消费 token 集合（SADD+EXPIRE pipeline 防永驻）
- 测试三层（CLAUDE.md §2）：
  - 单元 25 用例 PASS：schema 11 + jwt_service 8 + deep_link 5 + cookie 5 + role_router 8（不依赖 DB/Redis）
  - 集成 22 用例（含 20 并发同 jti 仅 1 胜出 race 测试 + 9 端点失败路径 + 10 jti service + 3 节点 hook）— 需真 PG/Redis；环境无故 SKIP
  - E2E 3 用例：20 并发 race / role isolation / cross_flow rejection
- 覆盖 ROADMAP §Phase 3 Success Criteria 1-5

#### Changed
- api/health.py Redis 从 not_checked 升级为真 ping
- NodeService 构造新增可选 redis 参数；DI 容器 get_node_service 注入
- main.py lifespan shutdown 加 dispose_redis
- api/errors.py 注册 AuthError 全局 handler
- .env.example Phase 3 段补全 SESSION_EXPIRY_HOURS / HTTPS_ENABLED / SESSION_COOKIE_NAME 占位
- .pre-commit-config.yaml mypy 加 types-redis 依赖

#### Security
- JWT_SECRET 启动校验：APP_MODE=prod 时拒绝默认占位值（防演示密钥上线）
- HS256 + pyjwt[crypto] dep（不用 python-jose，已 deprecated — SUMMARY R3）
- decode leeway=0 严格 exp 校验
- 失败统一 detail='鉴权失败'，不泄露具体 reason
- 集成测试用真 Redis + 真 PG 不 mock（CLAUDE.md §2.3 + 用户 memory feedback）

#### REQ Status
- AUTH-01 / AUTH-02 / AUTH-03 / AUTH-04 全部完成

#### Deferred to Future Phase
- 把 token 拼进邮件 → Phase 4 (NOTI-01/02)
- 前端 /flow/handle 静态壳页面 → Phase 5 (WEB-02)
- nginx log_format query 脱敏 → Phase 6 (PITFALLS #13)
- HTTPS 启用 + cookie secure=True 生效 → Phase 6
- API rate limiting (slowapi) → Phase 6
- JWT_SECRET 轮换机制 → v2
- SSO 替代演示用一键登录 → v2 (PROD-01)

### Added (Phase 2)

- 2026-05-16 — Phase 2 Plan 06：全流程 E2E 测试 + recover 工具集成测试
  - `tests/e2e/conftest.py`：复用 app_client fixture（HTTP / inline ASGI 双模式）
  - `tests/e2e/test_full_10_nodes_flow.py`：主路径 10 节点 happy-path
  - `tests/e2e/test_e2e_reject_paths.py`：3 个 reject 场景（manager / hr_initial / hr_final）
  - `tests/e2e/test_e2e_return_paths.py`：2 个 return 场景（hr_initial / applicant）
  - `tests/e2e/test_e2e_recover_from_db.py`：双写失败 → recover → 继续推进
  - `tests/integration/test_flow_full_chain.py`：真 PG + 真 PostgresSaver 双层一致性
  - `pyproject.toml` 注册 `integration` marker；默认 skip e2e + integration（通过环境变量启用）

### Phase 2 Complete (2026-05-16)

**交付**：
- ✓ 双写规范完整版（PRD §5.3.1 + PITFALLS #2）：业务事务 commit → graph.ainvoke → 失败 mark action_log.failed + raise HTTPException(500) + recover 提示
- ✓ scripts/recover_from_db.py CLI（--flow-id / --dry-run / --max-retries）
- ✓ flow_instances.context.node_results JSONB 应用层冗余（不依赖 LangGraph state）
- ✓ 10 节点全部实现：apply / manager_review / hr_initial / device_return / access_revoke / knowledge_handover / finance_settle / legal_sign / hr_final / applicant_final_confirm / archive
- ✓ 5 并行节点 fan-out（LangGraph 1.x Send）+ fan-in（自动 wait-all）
- ✓ 申请人最终确认节点（DF-02 ★★★★★）+ timeline 注入 interrupt payload + 两态决策（reject 防御性回退）
- ✓ 退回路径配置：hr_initial return → apply；applicant return → hr_final；hr_final return → device_return（v1 简化）
- ✓ 拒绝路径配置：manager_review / hr_initial / hr_final reject → END + flow.status=rejected
- ✓ services/timeline_renderer.py：纯函数渲染人类可读时间线（Phase 4 邮件 + E2E 复用）
- ✓ _human_node_factory：5 并行节点用工厂模板复用（每节点 < 20 行）
- ✓ routes.py：4 路由函数 + 节点名常量集中（避免循环 import）
- ✓ 126 测试（unit + 部分 integration / e2e skip）— Phase 1 35 + Phase 2 91 新增

**Phase 2 验收对应**（ROADMAP §Phase 2 Success Criteria）：
1. ✓ graph.invoke 抛异常 → action_logs.status='failed' → recover 可重试（test_e2e_recover_from_db + test_node_service_double_write）
2. ✓ 申请人节点 timeline 注入 interrupt payload（test_applicant_final_confirm）+ render_timeline 渲染完整 10 节点（test_timeline_renderer）
3. ✓ 退回路径正确（test_routes + test_e2e_return_paths）
4. ✓ 拒绝路径正确（test_routes + test_e2e_reject_paths）
5. ✓ 5 并行 fan-in（test_graph_topology + test_full_10_nodes_flow）

**Phase 2 不做的（已推到对应 phase）**：
- 鉴权 / JWT 一键登录 → Phase 3
- 邮件 / Mattermost / 真实通知发送 → Phase 4
- LLM 摘要（applicant 节点本 Phase 只准备 timeline）→ Phase 4
- 节点首次进入业务表自动 upsert（Plan 05 部分实现，完整版 Phase 4 配合通知场景再调整）

- 2026-05-16 — Phase 2 Plan 05：graph.py 总装 10 节点完整拓扑
  - apply → manager_review → hr_initial → 5 并行 (fan-out via Send) → hr_final → applicant_final_confirm → archive → END
  - `_route_after_hr_initial_to_parallel` 用 LangGraph 1.x `Send(node, state)` 实现 dynamic fan-out
  - 5 并行节点自动 fan-in（`add_edge(name, hr_final)` 多源默认 wait-all）
  - 退回 / 拒绝路径路由完整生效
  - `test_graph_topology.py`：9 测试（10 节点 / 5 并行 / archive→END / start→apply / fan-in / 编译 / 节点数 / manager_review interrupt）
  - 调整 `test_api_flows.test_advance_action_completes_manager_review_node`：Phase 2 拓扑下 manager_review 不再是末节点

- 2026-05-16 — Phase 2 Plan 04：applicant_final_confirm（DF-02 ★★★★★）+ archive + timeline_renderer
  - `flow_engine/nodes/applicant_final_confirm.py`：interrupt payload 含 timeline；两态决策（advance / return），reject 防御性回退到 advance；默认 actor=申请人；默认 result_text 视 action 而定
  - `flow_engine/nodes/archive.py`：自动节点（无 interrupt），actor=system:archivist
  - `services/timeline_renderer.py`：纯函数渲染人类可读时间线（前端 + Phase 4 邮件复用）
  - 24 测试：14 renderer + 7 applicant 节点 + 3 archive

- 2026-05-16 — Phase 2 Plan 03：5 并行节点 + _human_node_factory 工厂
  - `flow_engine/nodes/_human_node_factory.py`：人工节点通用模板（interrupt + decision + node_results）
  - 5 节点：device_return / access_revoke / knowledge_handover / finance_settle / legal_sign
  - `flow_engine/nodes/__init__.py` 暴露 `PARALLEL_NODES_META` 给 graph 总装
  - 20 测试：5 节点 × 3 行为（interrupt / advance / return）+ 5 元数据校验

- 2026-05-16 — Phase 2 Plan 02：hr_initial + hr_final 两个串行节点 + 路由函数模块
  - `flow_engine/nodes/hr_initial.py` / `hr_final.py`：interrupt + 三态决策模板
  - `flow_engine/routes.py`：4 路由函数（after_manager_review / after_hr_initial / after_hr_final / after_applicant）+ 11 节点名常量 + PARALLEL_NODES list
  - 23 测试：17 路由单测（覆盖每个分支）+ 6 节点 interrupt 行为单测

- 2026-05-16 — Phase 2 Plan 01：双写规范完整化（失败补偿 + node_results 应用层冗余 + recover_from_db.py CLI）
  - `ActionStatus` 新增 `PENDING`；`ActionRepository.mark_failed` / `mark_success` / `list_failed` 方法
  - `FlowRepository.append_node_result` 写 `flow_instances.context.node_results` JSONB 数组（业务层冗余，不依赖 LangGraph state）
  - `NodeService.submit_action` 升级：失败时 mark `action_log.failed` + 错误信息 + `raise HTTPException(500)` 含 recover 提示；成功时 mark success + graph 到 END 时 mark flow completed
  - `state_store/session.py` 暴露 `new_session()` 上下文管理器供失败补偿新开 session
  - `scripts/recover_from_db.py`：扫 failed action 重 invoke graph，支持 `--flow-id` / `--dry-run` / `--max-retries`
  - 测试：5 个 state_store 签名校验 + 5 个 double_write 集成测试（含 graph 失败 → action_log.failed 校验）+ 5 个 recover_from_db 单测
### Phase 1 Complete (2026-05-16)

**交付**：
- ✓ uv 项目骨架 + 完整 v1 依赖（langgraph / fastapi 0.136.1 / sqlalchemy 2.0.49 async / psycopg 3 / asyncpg / structlog 25.x / pydantic 2.13.4）
- ✓ pre-commit hooks（gitleaks v8.21.2 + ruff v0.8 + mypy v1.13 + check-yaml + no-commit-to-branch=main + check-merge-conflict + check-added-large-files）
- ✓ Docker Compose 编排（postgres 16-alpine 5433 / redis 7-alpine 6380 / flow-api 8000，全部 healthcheck + restart=unless-stopped + 独立 offboarding-net）
- ✓ 多阶段 Dockerfile（uv 0.10 builder + python 3.12-slim-bookworm runtime + wget 健康检查 + 缓存 mount）
- ✓ entrypoint.sh（alembic upgrade head → checkpointer.setup → uvicorn）
- ✓ 双 schema 隔离（app + langgraph + app_test + langgraph_test）+ deploy/init-db.sql + alembic env.py include_object 过滤 langgraph schema（PITFALLS #1）
- ✓ 6 张业务表 schema（flow_instances / node_states / action_logs / users / notifications / notification_outbox）+ Repository 层（含 PG ON CONFLICT upsert 幂等）
- ✓ LangGraph 引擎骨架（OffboardingState TypedDict + Annotated[list, operator.add] reducer 防 PITFALLS #4 + AsyncPostgresSaver psycopg 3 配置 PITFALLS #1 + 2 节点 apply/manager_review + dynamic interrupt + Command resume SUMMARY R3 + CLI --setup 入口）
- ✓ FastAPI 应用（lifespan 容错 + 统一 envelope {success,data,error,meta} + 全局 exception handler + /api/health 组件检查 + APP_MODE 启动 warning 日志 PITFALLS #10 + structlog dev/prod）
- ✓ 4 个业务 API 端点（POST /api/flows + GET /api/flows/{id} + GET /api/flows/{id}/nodes + POST /api/flows/{id}/nodes/{nid}/actions）
- ✓ 业务表与 LangGraph checkpoint 双写规范最小版（业务事务 commit → graph.ainvoke）
- ✓ 35 个测试全部通过（含 InMemorySaver 测 graph 流转 / asgi-lifespan + httpx 测 API / 重复推进 409 / 跨 flow_id 400 / 参数校验 422 / checkpoint 恢复 / Annotated reducer 静态校验）
- ✓ E2E 骨架 + 手动冒烟脚本（scripts/dev_up.sh + scripts/smoke_test.sh）
- ✓ frontend/tests/e2e/ Phase 5 占位骨架
- ✓ CHANGELOG 全程更新

**下一步**：
- **Phase 2**（双写规范完整化 + 节点函数完整化 + 申请人最终确认节点）— 把 manager_review 后的 8 节点 + 5 并行节点 + applicant_final_confirm 全部落地
- 或者：先在 192.168.2.44 上跑 `bash scripts/dev_up.sh && bash scripts/smoke_test.sh` 做一次部署冒烟

**Phase 1 不做的（已推到对应 phase）**：
- 鉴权 / 深链 JWT → Phase 3
- 邮件 / Mattermost / GLM 摘要 → Phase 4
- 前端 Next.js → Phase 5
- nginx / 超时扫描 / 完整部署 → Phase 6

### Added

- **2026-05-16** — **Phase 1 Plan 07**：E2E 测试骨架（backend/tests/e2e/test_full_flow.py 含 health + 起流程 + advance 的真容器冒烟 + docker restart 恢复占位 + 演示模式 11 场景占位清单 CLAUDE.md §2.1 + frontend/tests/e2e/ Phase 5 占位 + scripts/dev_up.sh + scripts/smoke_test.sh 手动冒烟 + pyproject.toml e2e marker 默认 skip）
- **2026-05-16** — **Phase 1 Plan 06**：API 业务集成（services/flow_service.py 含 create_flow 双写规范最小版 PRD §5.3 Pattern 1：业务事务（INSERT flow_instances + INSERT action_log + upsert apply/manager_review nodes）→ session.commit() → graph.ainvoke 跑到 interrupt 挂起 + services/node_service.py 含 submit_action 三态决策推进（advance/return/reject 映射 + 409 状态校验 + 业务事务 commit → graph.ainvoke Command resume）+ api/deps.py FastAPI Depends 容器 6 个工厂 + api/flows.py 3 个端点（POST/GET/GET nodes）+ api/nodes.py 三态决策端点 + 10 个集成测试覆盖 envelope shape/起流程/查询/双层状态分离/advance/reject/重复推进 409/未知 flow 404/参数校验 422 全通过）
- **2026-05-16** — **Phase 1 Plan 05**：FastAPI 应用骨架（config.py Pydantic Settings 单例 lru_cache + APP_MODE 启动 warning 日志 PITFALLS #10 + utils/logger.py structlog 配置 dev colorized / prod JSON + api/envelope.py {success,data,error,meta} helper + api/errors.py 全局 exception handler 含 RequestValidationError + Starlette HTTPException + Exception 兜底 + api/health.py 组件状态检查 db/graph/redis + main.py lifespan 串 init_db→build_graph→dispose 三件套 + 5 个集成测试 httpx+asgi-lifespan 全通过）
- **2026-05-16** — **Phase 1 Plan 04**：LangGraph 引擎骨架（OffboardingState TypedDict + Annotated[list, operator.add] reducer 防 PITFALLS #4 静默丢数据 + AsyncPostgresSaver 工厂含 psycopg 3 autocommit/dict_row/prepare_threshold=0 防 PITFALLS #1 deadlock + setup_checkpointer_schema CLI 入口 `python -m offboarding_flow.flow_engine.checkpointer --setup` 给 entrypoint.sh 调 DEPLOY-05 + 2 个最小节点 apply 自动节点/manager_review dynamic interrupt + Command resume 模式 SUMMARY R3 + graph.py StateGraph START→apply→manager_review→END 拓扑 + 6 个测试含 InMemorySaver checkpoint 恢复 + Annotated reducer 静态校验）
- **2026-05-16** — **Phase 1 Plan 03**：业务表 schema + Alembic + Repository 层（6 张 ORM 模型 flow_instances/node_states/action_logs/users/notifications/notification_outbox 全部 app schema + UUID PK gen_random_uuid + TIMESTAMPTZ 时间戳 + node_states.UNIQUE(flow_id, node_name) + notification_outbox.UNIQUE(flow_id, node_state_id, channel) 幂等基础 + alembic env.py include_object 过滤 langgraph schema 防 PITFALLS #1 误删 + version_table_schema=app + 异步 run_async_migrations + migration 0001 完整建表 + FlowRepository/NodeRepository/ActionRepository/UserRepository 含 PG ON CONFLICT upsert 接口 + 14 个单元测试覆盖模型/枚举/唯一约束/方法签名）
- **2026-05-16** — **Phase 1 Plan 02**：Docker 编排（docker-compose.yml 三服务 offboarding-postgres 5433 / offboarding-redis 6380 / flow-api 8000，全部 healthcheck + restart=unless-stopped + 独立 offboarding-net + volume `/data/offboarding/{postgres,redis}-data` 持久化 + docker-compose.dev.yml override 挂源码 + --reload + DEBUG）+ deploy/init-db.sql 创建 app/langgraph/app_test/langgraph_test 4 schema + 设 flow 角色 search_path=app,public + 多阶段 Dockerfile（uv 0.10 builder + python:3.12-slim-bookworm runtime + wget 健康检查 + venv 拷贝 + ENTRYPOINT entrypoint.sh） + backend/.dockerignore + entrypoint.sh 串联 alembic upgrade head → checkpointer.setup → exec uvicorn（DEPLOY-05）
- **2026-05-16** — **Phase 1 Plan 01**：初始化 backend/ uv 项目（pyproject.toml + uv.lock + .python-version + src layout）+ pre-commit hooks（gitleaks v8.21.2 + ruff v0.8.0 fix/format + mypy v1.13.0 + check-yaml + end-of-file-fixer + trailing-whitespace + no-commit-to-branch=main + check-merge-conflict + check-added-large-files）+ 扩展 .env.example 含 Phase 1 数据库/Redis/JWT/Mattermost/SMTP/MinIO/GLM 完整占位（不含真值）+ 更新 .gitignore（屏蔽 backend/.venv / htmlcov / coverage / .memsearch / .claude/settings.local.json）+ pytest 全局 conftest 含 loop_scope=session（防 PITFALLS #23）
- **2026-05-16** — 创建项目级 **`CLAUDE.md`**（AI 协作约定）：明确「能并行就并行开发」+ 「E2E 测试用 browser-harness」+ 项目特定的双层状态分离 / 节点幂等 / 演示模式 / 中文化等约束
- **2026-05-16** — Phase 1 `discuss-phase --auto` 完成：`.planning/phases/01-langgraph-schema/01-CONTEXT.md` 落盘，含 13 项实现决策（部署到 192.168.2.44 + 独立 postgres 容器端口 5433 + 双 schema 隔离 + dynamic interrupt + uv src layout 等）
- **2026-05-16** — PRD v0.4 大幅扩展（面试评分点对齐 + Mattermost @bot 入口 + AI 增强）：
  - 新增 §15 **AI 能力与边界声明**（含评分点对照表 + AI 推理下一步 LLM-04 + AI 后台报告 LLM-05 + AI 边界声明 LLM-06）
  - 新增 §16 **Mattermost @bot 入口**（8 个命令：start / status / report / suggest / list / help / simulate-timeout / simulate-evidence-missing）
  - 新增 §17 **任务逾期与证据缺失模拟**（demo 模式 3 分钟即触发 + 证据缺失检测）
  - 新增 §18 **加分项：自动动作节点演示**（AutoNode + mock-archive-service）
- **2026-05-16** — REQUIREMENTS.md v0.4：从 31 个 REQ 扩展到 **45 个 REQ**（新增 LLM-04/05/06 + BOT-01/02/03/04 + TIMEOUT-01/02/03/04 + AUTO-01/02/03 共 14 项）
- **2026-05-16** — ROADMAP.md v0.4：Phase 4 大幅扩展（4-5 天 → 6-8 天）+ 新增 **Phase 4.5 加分项自动动作节点** + Phase 5 加 TIMEOUT-04 标签
- **2026-05-16** — 初始化 GSD 项目结构（`.planning/`），生成 `PROJECT.md`（项目宪法）+ `config.json`（workflow 偏好：yolo / standard / balanced）
- **2026-05-16** — 启动 GSD 4 个并行研究 agent（stack / features / architecture / pitfalls），完成 `STACK.md`（36KB） / `FEATURES.md` / `ARCHITECTURE.md` / `PITFALLS.md`，待合成 `SUMMARY.md`
- **2026-05-16** — PRD v0.3 重大修订（详见 §0.3 changelog）：
  - `§4.2` 重写为「通用节点结构」：所有人工节点统一为「自由文本 result_text + 三态决策」，v1 不做差异化字段
  - `§4.5` 新增「申请人最终确认节点」：流程末尾自动聚合 node_results 邮件汇总给申请人本人
  - `§5.3` 新增「LangGraph runtime ≠ 业务表」澄清章节 + 节点函数双写模式 + 一致性约束
  - `§6.2` 重写「Token 一键登录」：完整 JWT payload + 6 步流程图 + 5 条安全约束 + 6 个角色视图差异表
  - `§7.4` 新增「测试 / 演示模式」：收件箱聚合 + 邮件主题角色前缀 + APP_MODE=demo/prod 开关
  - `§9.1` 新增「测试组织数据 seed 方案」：5 个 team + 8 个测试账号 + Mattermost Custom Attributes
  - `§10.0.1/§10.0.2` 新增「前端构建与部署策略」+ nginx 路由配置
  - `§10.1` 新增完整 `.env` 模板（含 Mattermost / QQ SMTP / 深链 JWT / DB / Redis 占位符）
- **2026-05-16** — 创建 `.gitignore`（屏蔽 `.env*` / `__pycache__` / `node_modules` / `.next` / `.DS_Store` 等）
- **2026-05-16** — 创建本 CHANGELOG.md

### Changed

- **2026-05-16** — PRD §10 部署配置：移除独立 `web` Next.js 运行时容器，改为「`next build` → 静态产物 → nginx 直接 serve」，简化部署链路

### Infrastructure

- **2026-05-16** — git init，设置远端 `git@github.com:LaiosOvO/liuxin-interview.git`，默认分支 `main`
- **2026-05-16** — 已部署 Mattermost 到 `http://192.168.2.44:8065`（team `laios`）

### Security Notes

- **2026-05-16** — QQ SMTP 授权码（16 位）+ GLM API Key 通过 `${VAR}` 环境变量注入，**未写入任何 git tracked 文件**
- **2026-05-16** — `.gitignore` 已屏蔽 `.env*` 模式

### Discovered / Planned (Not Yet Implemented)

> 来自研究 agent 的关键发现，待后续 phase 落地

- ⚠️ **深链 URL 格式可能需调整**：Next.js 15 `output: 'export'` + App Router 动态路径有已知问题（vercel/next.js#79380），STACK 研究推荐改为 query string `/flow/handle?flow_id=xxx&node_id=yyy&token=zzz`；ARCHITECTURE 研究给出 `useParams()` + `generateStaticParams() { return []; }` stub + nginx `try_files` 兜底的 workaround — 在 Phase 4 启动前需要决策
- ⚠️ **LangGraph 1.x API 更新**：推荐 `interrupt()` + `Command(resume=...)` 而非 PRD §8 用的 `interrupt_before`compile 参数；Phase 2 实现时按新 API
- ⚠️ **Node 版本**：pnpm 11 强制 Node 22+（PRD 写的 Node 20 需升级）
- ⚠️ **PRD §10.1 vs §10.0.2 配置不一致**：`DEEPLINK_BASE_URL=http://192.168.2.44:3000`（独立 web 端口）与 nginx 监听 :80 矛盾，应统一为 `http://192.168.2.44`（PITFALLS Pitfall 21）
- 📝 **outbox 模式**：通知发送不能在节点函数里同步 await（QQ SMTP 5-10s 卡顿会阻塞 graph），需 `notification_outbox` 表 + APScheduler 每 10s drain（Phase 4 落地）
- 📝 **PostgresSaver schema 隔离**：业务用 `app` schema + checkpoint 用 `langgraph` schema，alembic env.py 必须 `include_object` 过滤掉 langgraph，否则 autogenerate 会误删 LangGraph 表（Phase 1 落地）

---

## Conventions

### 入口

每次 GSD phase 完成、PRD 修订、git commit、`.planning/*` 落盘都应追加到 `[Unreleased]`。

### 分类

- **Added** — 新功能
- **Changed** — 现有功能变化
- **Deprecated** — 即将移除
- **Removed** — 已移除
- **Fixed** — bug 修复
- **Security** — 安全相关
- **Infrastructure** — 部署 / 基建变化
- **Discovered / Planned** — 研究发现，待实现

### 时间格式

`YYYY-MM-DD` 配合一行简述，必要时缩进列出细节。

### 版本切分

完成一个 milestone（如 M1 = backend 骨架跑通）时，从 `[Unreleased]` 切到 `[v0.1.0] - 2026-MM-DD`。
