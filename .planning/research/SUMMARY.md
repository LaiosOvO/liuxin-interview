# Project Research Summary — AI 驱动的离职流程执行系统

**Project:** offboarding-flow (LangGraph + FastAPI + Next.js 状态机驱动的 HR 离职流程)
**Domain:** State-machine workflow engine（流程引擎流派，非业务系统流派）
**Researched:** 2026-05-16
**Confidence:** HIGH（STACK / ARCHITECTURE / PITFALLS 主线均有官方文档背书；FEATURES 行业模式 MEDIUM-HIGH）

> 本 SUMMARY 是 4 份并行研究（STACK / FEATURES / ARCHITECTURE / PITFALLS）的合成结果，目的是为后续 REQUIREMENTS / ROADMAP 生成提供可直接采纳的决策摘要。详细论据见对应研究文件；本文只摘核心结论、PRD 修订建议、合并后的 phase 推荐和置信度。

---

## Executive Summary

本项目是一个**状态机驱动的人工审批流程引擎**（流程引擎流派，对标 Camunda / Temporal / LangGraph），借「8 角色 10 节点的离职流程」作为可演示场景，端到端呈现「双层状态分离 + 人工中断恢复 + 双通道通知 + 一键登录 + 三态决策 + 申请人闭环」。研究确认 PRD 的核心定位（**不是 ChatBot、不是业务系统、不是可视化编排**）与行业流程引擎流派完全一致，table stakes 12/12 已覆盖，3 个★★★★★ 差异化亮点（双层状态分离 / 申请人最终确认 / LLM 末端摘要）全部在 v1 范围内。 [Source: FEATURES]

**推荐技术选型**保持 PRD 已锁定的 LangGraph 1.2.0 + FastAPI 0.136.1 + SQLAlchemy 2.x async + Next.js 15 静态导出 + Tailwind v4 + Docker Compose v2；研究新增推荐 **uv / pyjwt / aiosmtplib / openai 包指向智谱 base_url / polyfactory / APScheduler / outbox 模式**。**架构推荐 single-process monolith + 单 Postgres（双 schema）+ 单 Redis**，零分布式队列；通知通过 outbox 模式异步发送避免 QQ SMTP 5-10s 卡顿阻塞 graph；LangGraph 用动态 `interrupt()` + `Command(resume=...)` 而非旧的 `interrupt_before`。 [Source: STACK, ARCHITECTURE]

**4 份研究**一致发现 PRD v0.3 存在 **6 处必修订项**（详见 §5），最关键的是 **DEEPLINK_BASE_URL 配置矛盾（:3000 vs :80）+ 深链 URL 格式不兼容 Next.js 15 静态导出**——这些必须在 P3 / P5 实现前在 PRD 里改掉，否则 demo 跑不通。剩余风险集中在 LangGraph 双写一致性、interrupt 重跑副作用幂等、jti 黑名单 race、Mattermost 内网 callback 防火墙、QQ SMTP 频率限制 —— 全部有对应 prevention，PITFALLS.md 已给出代码模板。 [Source: PITFALLS, STACK, ARCHITECTURE]

---

## Key Findings

### Recommended Stack

详见 [STACK.md](./STACK.md)。PRD 锁定项全部得到 2026-05 当下版本核对验证；研究新增的关键推荐项均有官方文档背书。

**Core technologies（PRD 已锁定，研究确认 HIGH confidence）：**
- **LangGraph 1.2.0 + langgraph-checkpoint-postgres 3.1.0**: 状态机引擎 + 人工中断 + checkpoint 持久化 — 1.x 是 production-ready GA 版本，2026-05-12 发布 [Source: STACK]
- **FastAPI 0.136.1 + Pydantic v2**: ASGI Web 框架 + 校验 — 2026-04-23 发布 [Source: STACK]
- **SQLAlchemy 2.x async + asyncpg 0.30+**: DSN 必须用 `postgresql+asyncpg://` [Source: STACK]
- **Next.js 15 LTS + React 19 + Tailwind v4 + shadcn/ui**: 静态导出 + 现代 React — Next.js 15 LTS 到 2026-10-21 [Source: STACK]
- **PostgreSQL 16-alpine + Redis 7-alpine + nginx 1.27-alpine + Docker Compose v2**: 单实例双 schema [Source: STACK, ARCHITECTURE]

**Core technologies（研究新增推荐，未在 PRD 中显式提及）：**
- **uv**（包管理）: 2026 主流 — 用户全局规则已强制 [Source: STACK]
- **pyjwt[crypto] 2.10+**: 替代已 deprecated 的 python-jose — FastAPI 官方 discussion #11345 已移除推荐 [Source: STACK]
- **aiosmtplib 5.1.x + Jinja2 3.1.x**: 异步 SMTP + HTML 模板，QQ 邮箱 `port=465 + use_tls=True`（implicit TLS）[Source: STACK]
- **openai 包指向智谱 base_url**: `base_url="https://open.bigmodel.cn/api/paas/v4/"` — 未来切模型零代码改动 [Source: STACK]
- **psycopg[binary] 3.2+**: langgraph-checkpoint-postgres 底层依赖；与业务 asyncpg 并存 [Source: STACK]
- **APScheduler AsyncIOScheduler**: 进程内 scheduler 跑超时扫描 + outbox drain — v1 单进程足够 [Source: ARCHITECTURE]
- **polyfactory**: 替代 factory-boy，原生支持 Pydantic v2 / SQLAlchemy 2 async [Source: STACK]
- **structlog + tenacity + httpx 0.28+**: 标配支持库 [Source: STACK]

**明确禁用项**（详见 STACK.md §6）: Poetry / pip-tools / SQLAlchemy 1.x / Flask / python-jose / factory-boy / moment.js / alpine 镜像跑 Python / psycopg2 / Tailwind v3 / pnpm ≤10 / docker-compose v1 / `interrupt_before` 旧 API / 非 `+asyncpg` DSN

### Expected Features

详见 [FEATURES.md](./FEATURES.md)。研究采用「**红线测试**」分类: "如果换成请假流程 / 报销流程，这个能力还成立吗？" — YES 则是流程引擎能力（要做），NO 则是业务系统能力（不做）。

**Must have (table stakes, 12/12 已覆盖)：**
- 状态机引擎 + checkpoint 持久化（TS-01, FLOW-01/03）
- 人工任务中断 + 恢复（TS-02, AUTH-02）
- 三态决策 + 退回路径配置（TS-03/12, FLOW-04/05）
- DAG + 并行 fan-out/fan-in（TS-04, FLOW-01）
- 按人/角色 assignee + 邮件通知（TS-05/06, NOTI-01）
- 审计 / action history append-only（TS-07）
- 进度可视化时间线 + 流程列表查询（TS-08/10, WEB-04/05）
- 崩溃恢复 durable execution（TS-09, FLOW-03）

**Should have (★★★★★ 差异化亮点，全部在 v1)：**
- **DF-01 双层状态分离**：LangGraph runtime ≠ 业务表 — 项目最深的设计决策 [Source: FEATURES, ARCHITECTURE]
- **DF-02 申请人最终确认节点**：流程对全角色闭环 [Source: FEATURES]
- **DF-08 LLM 用作末端摘要**：反 ChatBot 的克制设计，失败降级不阻塞流程 [Source: FEATURES]
- **DF-03 邮件深链 magic link + jti 一次性**：passwordless 等价 SSO [Source: FEATURES]
- **DF-06 演示模式统一收件箱 + 角色前缀**：一位演示者演 8 角色的工程化解法 [Source: FEATURES]

**Defer (v2+ 明确不做，17 项 anti-features)：**
- 与外部业务系统真实 API 集成（资产 / AD / 财务）— NOT-02
- 每节点差异化表单 / 字段 — NOT-01
- 流程模板可视化编排 — NOT-03
- 多种离职流程模板 — NOT-04
- 节点附件上传 / 子流程 / SSO / 企业微信 / 移动端 / i18n / 多租户 / 可视化状态机图 / ChatBot 风格 / RBAC 配置后台 / 节点回滚 / BI 报表 / agent 自动节点

**Scope creep 红线**：17 条 anti-features 任一进入 v1 都会爆 3 周时间预算。 [Source: FEATURES]

### Architecture Approach

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。**一句话架构**：一个 FastAPI 进程托管 LangGraph 引擎，业务表与 PostgresSaver checkpoint 共库不同 schema 双写；人工节点通过 `interrupt()` 挂起，邮件深链携带一次性 JWT 唤醒，Cookie 鉴权后 `Command(resume=...)` 推进；Next.js 静态导出 + nginx 反代提供前端；APScheduler 同进程跑超时扫描，通知发送走轻量 outbox。

**Major components:**
1. **flow_engine (LangGraph)** — DAG 编排、checkpoint 持久化、`interrupt()` 挂起、`Command(resume=...)` 恢复、并行 fan-out/fan-in；全局单例
2. **state_store (Repository)** — 业务表唯一访问路径，封装事务边界；所有 UI 数据源（不读 LangGraph checkpoint）
3. **notifications (outbox + dispatcher + outbox_worker)** — 节点函数事务内写 outbox，APScheduler 每 10s drain 调用 SMTP / Mattermost
4. **auth (JWT + jti 黑名单 + cookie)** — Redis `SET NX EX` 原子操作消费 jti；HttpOnly Cookie + SameSite=Lax
5. **scheduler (APScheduler in-process)** — 超时扫描（每分钟）+ outbox drain（每 10s）
6. **frontend (Next.js 15 静态导出)** — `'use client'` + `useParams` + fetch；nginx 直接 serve `out/`
7. **nginx** — 反代 `/api/` + `/ws/`；`try_files /index.html` 兜底前端路由

**8 个关键架构 Pattern**（详见 ARCHITECTURE.md §3）：双层状态 + 节点函数双写 / Dynamic interrupt / 业务表与 LangGraph schema 同实例隔离 / 并行 fan-out + Annotated reducer / 通知轻量 outbox / JWT 一键登录 + 一次性 jti / APScheduler in-process / Next.js 静态导出 + 客户端动态路由

### Critical Pitfalls

详见 [PITFALLS.md](./PITFALLS.md)（28 个 pitfall，11 个 Critical / 12 个 Moderate / 5 个 Minor）。

**Top 5（按"破坏性 × 易犯性"排序）：**

1. **节点函数双写不一致（Pitfall #2）** — 业务表写成功但 LangGraph invoke 失败，流程卡死 → 必须先 commit 业务事务，再 invoke LangGraph，失败时 mark action_log.failed 并提供 retry 路径 [Source: PITFALLS]
2. **interrupt 重跑副作用不幂等（Pitfall #16, #3）** — 节点函数被重试时重复发邮件 → 所有写入用 upsert，outbox 表 `UNIQUE(flow_id, node_state_id, channel)` [Source: PITFALLS, ARCHITECTURE]
3. **JWT 双击 race condition（Pitfall #6）** — 双击邮件按钮，2 个 tab 都通过 jti 校验 → 必须用 Redis `SET ... NX EX` 原子操作 [Source: PITFALLS]
4. **Mattermost callback 被 SSRF 防护拦截（Pitfall #7）** — 内网 IP 默认黑名单 → 配置 `AllowedUntrustedInternalConnections=192.168.2.44 flow-api localhost`；seed 脚本启动校验 [Source: PITFALLS]
5. **凭证泄露 / 演示模式上线（Pitfall #8, #10）** — `.env` 真值进 git / `APP_MODE=demo` 没切回 → 第一个 commit 之前必有 `.gitignore` + pre-commit gitleaks；启动 log 显式打印 mode [Source: PITFALLS]

---

## 5. Required PRD Revisions（4 份研究一致发现的 6 处必修订项）

> 这是本 SUMMARY 最重要的一节。下游 REQUIREMENTS / ROADMAP 阶段必须先用这些修订更新 PRD v0.3 → v0.4，否则 demo 跑不通或代码与文档不一致。

| # | PRD 位置 | 问题 | 必修订内容 | 来源 | 严重度 |
|---|---------|------|-----------|------|-------|
| **R1** | PRD §10.1 `DEEPLINK_BASE_URL=http://192.168.2.44:3000` | 配置矛盾：PRD §10 nginx 在 80 端口反代，没有 :3000 服务；用户点深链跳 :3000 → "无法连接" | 改为 `DEEPLINK_BASE_URL=http://192.168.2.44`（无端口或显式 :80） | STACK §3 + ARCHITECTURE §6.3 + PITFALLS #21 | **致命** |
| **R2** | PRD §10.0.1 / §6.2 深链格式 `/flow/[flow_id]/node/[node_id]?token=xxx` | Next.js 15 App Router + `output: 'export'` 下 path param 动态路由 build 失败 / `useParams()` 运行时不稳定（vercel/next.js#79380）| **推荐方案 A（改 URL 格式）**：`/flow/handle?flow_id=xxx&node_id=yyy&token=zzz`，单一静态壳页面 + `useSearchParams()` 完全工作。后端 `build_deep_link` 同步调整。**或方案 B（保留 path）**：`generateStaticParams()=[]` + `dynamicParams=true` + nginx 兜底，但社区报告 race condition | STACK §2.3 + ARCHITECTURE §3 Pattern 8 + PITFALLS #19 | **致命** |
| **R3** | PRD §8.1 LangGraph 用 `interrupt_before=[...]` + `graph.update_state(...)` + `graph.invoke(None)` | 2026 LangGraph 1.x 推荐 dynamic `interrupt()` + `Command(resume=...)`，避免在上游节点写下游 state 的职责拧巴 | 节点函数内 `decision = interrupt({...})` 挂起，API 层用 `graph.ainvoke(Command(resume={action, result_text, reason}), config={...})` 恢复。所有节点函数必须**幂等**（interrupt 抛 GraphInterrupt 会重试） | STACK §4.1 + ARCHITECTURE §3 Pattern 2 + PITFALLS #16 | **致命** |
| **R4** | PRD §10 部署架构（未显式说明 alembic 与 LangGraph schema 关系）| `alembic revision --autogenerate` 会把 LangGraph `checkpoints` 表也扫进去，与 `AsyncPostgresSaver.setup()` 自管表冲突 | PRD §10.2 启动顺序新增：「业务表用 alembic（schema=app），LangGraph checkpoint 表由 `await checkpointer.setup()` 自管（schema=langgraph）；alembic env.py `include_object` 必须过滤 `schema == 'langgraph'`」；entrypoint.sh: alembic upgrade head → saver.setup → uvicorn | STACK §1.2 + ARCHITECTURE §3 Pattern 3 + PITFALLS #1 | 改进 |
| **R5** | PRD §10 / §5.3.1 节点函数直接 `await send_email(...)` | QQ SMTP 偶发 5-10s 卡顿会阻塞 graph 推进 | 改为 **outbox 模式**：节点函数事务内 `INSERT INTO notification_outbox(...)`；APScheduler `outbox_drain` job 每 10s 拉 pending 调 SMTP / Mattermost；outbox 表加 `UNIQUE(flow_id, node_state_id, channel)` 幂等保护 | ARCHITECTURE §3 Pattern 5 + PITFALLS #14 | 改进 |
| **R6** | PRD §10 没有明确 Node.js 版本；未锁 pnpm | pnpm 11 强制要求 Node 22+；锁版本避免环境漂移 | 新增约束：**Node.js 22 LTS + pnpm 11.1.1**（写入 `package.json` 的 `packageManager: "pnpm@11.1.1"`）；Backend 锁 Python 3.12+ | STACK §2.1 | 改进 |

**额外建议（非必修订，但建议在 PRD 加注释）：**
- **R7**: PRD §5.3 明确写明「业务表为 source of truth，崩溃后从业务表重建 LangGraph state；提供 `scripts/recover_from_db.py`」(已隐含在 §5.3.2)
- **R8**: PRD §6.2.2 一键登录链路第 2 步「校验 jti 未消费」明确改为「**Redis `SET ... NX EX` 原子操作**」
- **R9**: PRD §10.0.2 nginx `location /api/` 加 `^~` 修饰符避免被正则吞掉；`log_format` 不记录 query string 防 token 进日志

---

## Implications for Roadmap

### 合并后的推荐 Phase 拆分（6 phase 主线 + 子拆分）

> **关键合成决策**：4 份研究的 phase 建议不一致 — ARCHITECTURE 给 11 phase（P1-P11，精细到 P5a-P5d），FEATURES 给 6 phase（按 feature 类簇），PITFALLS 映射到 6 phase（P1-P6），STACK 用 "Phase 1 = Backend 骨架 + LangGraph + Docker 编排" 作论据。
>
> **合成方案**：采纳 **PITFALLS / FEATURES 的 6 phase 主线**（粒度适合 3 周交付，每个 phase 独立可演示），P5 内部按 ARCHITECTURE P5a-P5d 子拆分保留 demo milestone 可见性。

#### Phase 1: 基建 + LangGraph 骨架 + 业务表 schema（约 3-4 天）

**Rationale:** 状态机 + checkpoint + Docker 编排基座；所有后续 phase 的依赖。4 份研究一致建议 P1 优先 — PITFALLS 9 个 Critical 中有 5 个属 P1。

**Delivers:**
- uv 项目骨架 + pyproject.toml + Pydantic Settings + `.env.example` + `.gitignore` + pre-commit gitleaks（第一个 commit 之前必有, PITFALLS #8）
- Postgres + Redis docker-compose（业务 schema `app` + LangGraph schema `langgraph`, `search_path` 隔离, ARCHITECTURE §3 Pattern 3）
- Alembic async 模板 + 业务表 migration（flow_instances / node_states / action_logs / notifications / notification_outbox / users）
- LangGraph `StateGraph` + `AsyncPostgresSaver`（`autocommit=True + row_factory=dict_row + prepare_threshold=0`, PITFALLS #1）
- `OffboardingState` TypedDict + `Annotated[list, operator.add]` reducer（PITFALLS #4）
- 2 个最小节点（apply + manager_review）+ dynamic `interrupt()` + `Command(resume=...)`
- `POST /api/flows` + `POST /api/flows/{id}/nodes/{id}/actions`（先不鉴权）
- pytest fixture loop_scope=session（PITFALLS #23）
- `flow_id` 强制 uuid4()（PITFALLS #17）

**Addresses:** FLOW-01/03, DEPLOY-01/02/03/04
**Avoids:** PITFALLS #1/#4/#5/#8/#17/#23
**Verification:** uvicorn 起得来 → `/api/health` 200 → curl 起流程 → curl advance → 推进；docker restart 后能从 interrupt 恢复

#### Phase 2: 业务表双写规范 + 节点函数完整化 + 申请人最终确认节点（约 3-4 天）

**Rationale:** P1 跑通最小双节点后，把"节点函数双写 + 退回路径 + 申请人最终确认"核心契约实现完整；这是项目最深的设计决策（DF-01 + DF-02 ★★★★★）。

**Delivers:**
- 节点函数 `is_first_entry` 判断 + upsert 幂等（PITFALLS #16）
- node_service.submit_action: 业务事务 commit → graph.ainvoke(Command) → 失败 mark action_log.failed + alert（PITFALLS #2）
- 三态决策 + 退回路径配置（FLOW-04/05）
- 申请人最终确认节点 `applicant_final_confirm` + `context.node_results[]` 聚合（FLOW-06 = DF-02 ★★★★★）
- 10 个节点全部实现 + 并行 fan-out + fan-in
- `scripts/recover_from_db.py` 工具

**Addresses:** FLOW-02/04/05/06 (DF-01/02/07)
**Avoids:** PITFALLS #2/#3/#16
**Verification:** 跑到任意节点 → 故意 invoke 失败 → action_log.status=failed 可见 → recover 脚本可重试；申请人邮件聚合显示全 10 节点结果

#### Phase 3: 鉴权 + 深链 JWT 一键登录 + jti 一次性（约 2-3 天）

**Rationale:** 通知里要带 token 链接，必须先有 token 签发 + 校验能力；放在 P4 通知之前是因果依赖。

**Delivers:**
- JWT 签发 / decode（pyjwt HS256）+ `POST /api/auth/exchange` token → session cookie
- Redis `SET ... NX EX` 原子消费 jti（PITFALLS #6）
- HttpOnly Cookie + `SameSite=Lax`（不能 Strict, PITFALLS #12）
- `secure=(APP_MODE=="prod" and HTTPS_ENABLED)`（内网 HTTP 不能开 Secure）
- 节点状态变更时清掉该 node 所有未消费 token
- role 校验 Depends + (flow_id, node_id, sub) 三元组绑定校验
- **若采纳 R2 方案 A**: 深链改为 query string 格式

**Addresses:** AUTH-01/02/03/04 (DF-03)
**Avoids:** PITFALLS #6/#12/#13
**Verification:** `asyncio.gather(exchange, exchange)` 并发同一 token 必须只有一个 200

#### Phase 4: 通知双通道 outbox + Seed 脚本 + LLM 摘要降级（约 4-5 天）

**Rationale:** 鉴权打通后，把"通知发送 + 演示组织数据 + LLM 摘要"作为完整的"消息能到达"phase。LLM 与核心流程解耦放在这里因为申请人确认节点 P2 已就绪。

**Delivers:**
- `notification_outbox` 表 + outbox 模式（事务内 enqueue, R5）
- `email_sender` (aiosmtplib + QQ SMTP 465 + SSL + 授权码, PITFALLS #14)
- `EmailEnvelope` 演示 / 生产差异；`APP_MODE=demo` 主题加 `[角色·username]` 前缀 + 正文加横幅（PITFALLS #10）
- 中文主题 RFC 2047 编码（用 `EmailMessage`, PITFALLS #15）
- HTML 邮件 table-based 模板（PITFALLS #24）
- `mattermost_sender` (httpx + Bot Token) + Interactive Message 卡片
- Mattermost `AllowedUntrustedInternalConnections` 配置 + seed 校验（PITFALLS #7）
- Bot Token vs System Admin PAT 分离（PITFALLS #18）
- APScheduler outbox_drain + timeout_scan job
- `seed_demo_data.py` 幂等（ensure_user/ensure_team 用 GET-then-create, PITFALLS #11）
- GLM client (openai 包 + 智谱 base_url) + `asyncio.timeout(8)` + 失败降级（PITFALLS #22）
- QQ SMTP 节流 + callback URL 加 secret 防 SSRF 伪造

**Addresses:** NOTI-01/02/03/04 + LLM-01/02/03 + SEED-01/02/03 (DF-05/06/08 ★★★★★)
**Avoids:** PITFALLS #7/#10/#11/#14/#15/#18/#22/#24/#26
**Verification:** curl 起流程 → 10s 内 QQ 邮箱收到带角色前缀邮件；故意把 GLM_API_KEY 设错 → 申请人邮件无摘要但能发出；seed 跑两次 0 错误

#### Phase 5: 前端 Next.js + 多角色页面 + 申请人时间线 + HR Dashboard（约 4-5 天）

**Rationale:** 邮件能发出后才有真实闭环，前端开发能验证"点 → 登录 → 决策"链路。子拆分按 ARCHITECTURE P5a-P5d。

**Sub-phases:**
- **P5a**: Next.js 15 init / Tailwind v4 / shadcn/ui / `output: 'export'` / 一键登录页
- **P5b**: NodeForm 通用三态表单 + 决策提交（颜色区分：继续=蓝 / 退回=黄 / 拒绝=红 + confirm dialog）
- **P5c**: `/my/flows` + `/hr/dashboard` + 卡点筛选 + **"重发通知"按钮**（PITFALLS #27）
- **P5d**: ApplicantConfirm 含时间线 + GLM 摘要段 + 仅"确认/退回"按钮

**Delivers:**
- 若 R2 方案 A: `app/flow/handle/page.tsx` 单一静态壳页面 + `useSearchParams`
- 若 R2 方案 B: `[flow_id]/[node_id]/page.tsx` + `generateStaticParams=[]` + `dynamicParams=true`（PITFALLS #19）
- 所有页面 `'use client'`（PITFALLS Anti-Pattern 7）
- 页面 banner 显示"当前角色：xxx（username）"
- SWR + react-hook-form + zod

**Addresses:** WEB-01/02/03/04/05 (DF-04)
**Avoids:** PITFALLS #19/#27 + UX 按钮无区分
**Verification:** `pnpm build` 0 error；客户端路由刷新不 404

#### Phase 6: 部署 + 演示模式切换 + 超时扫描 + 运维脚本 + 演示打磨（约 2-3 天）

**Rationale:** 开发期本地 PG/Redis + uvicorn 迭代快；最后一步打镜像 + 部署 + 演示前打磨。

**Delivers:**
- 后端 Dockerfile 多阶段（uv builder + slim-bookworm runtime, STACK §3.2）
- docker-compose.yml（healthcheck + depends_on + restart）
- nginx.conf（`location ^~ /api/` + `try_files /index.html` + log_format 不记录 query, PITFALLS #20/#13）
- entrypoint.sh: alembic upgrade head → saver.setup → uvicorn（R4）
- `extra_hosts: host-gateway` 让容器访问宿主机 Mattermost :8065（PITFALLS #21）
- 修正 `DEEPLINK_BASE_URL` 不带 :3000（R1）
- APScheduler timeout_scan（NOTI-05）
- dev-restart.sh / dev-reset.sh 二次确认（PITFALLS #9）
- cleanup_old_checkpoints.py（PITFALLS #25）
- 启动 log 显式打印 APP_MODE；前端 footer 显示 mode（PITFALLS #10）
- 演示 runbook + E2E + 讲稿 + 录屏

**Addresses:** DEPLOY-01/02/03/04 + NOTI-05 (DF-09)
**Avoids:** PITFALLS #9/#10/#13/#20/#21/#25/#28
**Verification:** `docker compose up -d` 一键起来；E2E 通过；"Looks Done But Isn't" Checklist 全过

### Phase Ordering Rationale

**核心依赖链**（4 份研究一致）：状态机 → 双写 + 申请人闭环 → 鉴权 → 通知 → 前端 → 部署打磨。

**关键 sequencing 决策**：
- P3 鉴权放在 P4 通知之前：通知里要带 token 链接 [Source: ARCHITECTURE]
- P5 前端放在 P4 通知之后：必须先有真实邮件能点，前端才能闭环验证 [Source: ARCHITECTURE, FEATURES]
- P2 申请人最终确认放在 P4 LLM 之前：节点框架先就绪，LLM 摘要只是末端可选增强 [Source: FEATURES, PITFALLS]
- 并行节点放在 P2 而不是更早：单线流程跑通后再加并行复杂度 [Source: ARCHITECTURE]
- Docker 完整部署放最后：开发期本地迭代快 [Source: ARCHITECTURE]

每个 phase 完成后系统都应是**可运行可演示**的。

### Research Flags（哪些 phase 需要 plan-phase 深入研究，哪些可直接动工）

| Phase | 置信度 | 是否需要 `/gsd:research-phase` |
|-------|--------|------------------------------|
| **P1** 基建 + LangGraph 骨架 | **HIGH** | 不需要 — STACK + ARCHITECTURE + PITFALLS 已给出完整代码模板 |
| **P2** 双写规范 + 申请人确认 | **HIGH** | 不需要 — ARCHITECTURE §3 Pattern 1 + PITFALLS #2/#16 已给出双写时序代码 |
| **P3** 鉴权 + 深链 | **HIGH** | 不需要 — STACK §4.4 + ARCHITECTURE §3 Pattern 6 + PITFALLS #6/#12 已给出完整方案；**但 R2 必须在 plan-phase 最终敲定方案 A vs B** |
| **P4** 通知 outbox + LLM + Seed | **MEDIUM** | 部分需要 — Mattermost Interactive Message callback 接收 + Custom Attributes seed 在 v1 落地细节覆盖度 MEDIUM；**建议 P4 启动前花半天做 Mattermost API POC** |
| **P5** 前端 Next.js | **MEDIUM** | 部分需要 — Next.js 15 + Tailwind v4 + shadcn/ui 是 2026 新栈；**R2 深链格式直接决定 P5a 实现路径**；建议 1 天前端骨架 POC |
| **P6** 部署 + 演示打磨 | **HIGH** | 不需要 — STACK §3 + ARCHITECTURE §11 + PITFALLS deploy 类已给出完整模板 |

**单独建议**：
- **R2 深链 URL 格式（方案 A vs B）必须在 P3 实施前敲定**。强烈推荐方案 A（query string）— Next.js 15 issue #79380 表明方案 B 长期不稳定；方案 A 唯一影响是 URL 不再 RESTful。
- **GLM API 智谱 base_url 兼容性 POC**：v1 启动前花 30 分钟验证 `openai` 包能调 `glm-4.6`。不通则降级到 `zhipuai` SDK。

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | **HIGH** | 关键版本号在 PyPI / npm / 官方文档 2026-05-16 当下直接核对；唯一 MEDIUM 是 openai 包指向智谱 base_url 兼容性 + mattermostautodriver vs httpx 直调取舍 |
| **Features** | **MEDIUM-HIGH** | 国际流程引擎 + 西方 HR offboarding HIGH；中国 HR SaaS 细分功能 LOW（但不影响方向）。table stakes 12/12 + diff 10/10 + anti-features 17/17 完整覆盖 |
| **Architecture** | **HIGH** | LangGraph / FastAPI / Postgres / JWT 主线均有 2026 主流文档背书；Next.js static-export 动态路由部分 MEDIUM（依赖 R2 决策） |
| **Pitfalls** | **HIGH** | 28 个 pitfall 多数验证自官方文档 + GitHub issues；演示场景类基于 PRD 推导 MEDIUM 但 prevention 都有代码模板 |

**Overall confidence:** **HIGH**

### Gaps to Address

以下 4 个 gap 在 plan-phase 阶段需明确，但不阻塞 roadmap 创建：

1. **R2 深链 URL 格式最终决策（方案 A vs B）** — 强烈推荐方案 A
2. **GLM API 智谱 base_url 兼容性 POC** — 30 分钟小 POC
3. **Mattermost Interactive Message callback 接收路径** — v1 可只做"跳转 URL"不接 callback
4. **LangGraph checkpoint schema 隔离 + alembic include_object 配置** — R4 已明确，实施时需文档化注释

---

## Sources

### Primary (HIGH confidence)
- **LangGraph 官方**: langgraph 1.2.0 PyPI / langgraph-checkpoint-postgres 3.1.0 / Interrupts docs / use-graph-api / AsyncPostgresSaver API
- **FastAPI / Pydantic**: FastAPI 0.136.1 PyPI / Async Tests docs / discussion #11345 python-jose 移除
- **Next.js**: endoflife.date Next.js 15 LTS / Static Exports docs / issue #79380 / generateStaticParams docs
- **Mattermost**: AllowedUntrustedInternalConnections 官方 / Interactive Messages plugin docs / forum #19250 address forbidden
- **Pattern**: Microservices.io Transactional Outbox
- **shadcn**: shadcn/ui Tailwind v4 docs
- **uv**: uv Docker integration
- **Alembic**: async cookbook
- **Security**: OWASP HttpOnly / MDN Cookies Secure
- **LangGraph issues**: #7780 interrupt loop / #1800 async + sync invoke hang / #1138 checkpoint 无界增长

### Secondary (MEDIUM confidence)
- LangGraph vs Temporal 2026 / LangGraph Best Practices / LangGraph Persistence Guide 2026 / Camunda 8 Parallel Gateway docs / Magic Links Security Deep Dive 2026 / Cflow HR Approval Patterns / GLM 4.6 API Deployment / APScheduler vs Celery Beat / OneUptime JWT Blacklist with Redis 2026

### Tertiary (LOW confidence)
- 中国 HR SaaS 细分功能 — 不影响项目方向，仅作 Q2 三态决策行业背景论据

---

*Research synthesis completed: 2026-05-16*
*Ready for: REQUIREMENTS → ROADMAP（建议 roadmapper 先用 §5 Required PRD Revisions 把 PRD 升级到 v0.4，再基于 §Implications for Roadmap 的 6 phase 拆分生成 roadmap）*
