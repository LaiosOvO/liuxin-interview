# offboarding-flow

> AI 驱动的离职流程执行系统 — 面试演示项目

## What This Is

一个**状态机驱动**的离职流程执行系统，不是 AI 聊天助手。HR 提交离职申请后，系统按 DAG 自动推进上级审批 / HR 初审 / 设备归还 / 权限回收 / 知识交接 / 财务结算 / 法务签字 / HR 终审 / 申请人最终确认 / 归档 共 10 个节点；每个人工节点通过邮件 + Mattermost 双通道通知责任人，邮件深链携带 JWT token 实现**一键登录免账号密码**，责任人填写自由文本结果 + 三态决策（继续 / 退回 / 拒绝）后驱动 LangGraph 推进。

面向人群：本人面试演示用，一位演示者扮演 8 个角色（员工 / 上级 / 总监 / HR×2 / IT / 财务 / 法务），所有邮件统一发到 `1624456575@qq.com` 同一收件箱。

## Core Value

**让"流程状态机"端到端可见且可驱动**：一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进到下一节点，直到申请人收到聚合所有节点执行内容的最终确认邮件。这是流程平台的本质能力，不是业务系统的能力。

## Requirements

### Validated

<!-- 尚未发布，空 -->

(None yet — ship to validate)

### Active

#### 流程引擎

- [ ] **FLOW-01**: 离职流程 DAG 用 LangGraph StateGraph 定义，10 个节点 + 并行扇出扇入
- [ ] **FLOW-02**: 节点函数自动同步写入业务表 `node_states` / `action_logs` / `flow_instances`
- [ ] **FLOW-03**: 进程崩溃后能从 PostgresSaver checkpoint 恢复执行
- [ ] **FLOW-04**: 每个人工节点统一为「自由文本 `result_text` + 三态决策 (advance / return / reject)」
- [ ] **FLOW-05**: 三态决策的退回路径按流程模板配置，拒绝在关键节点触发流程终止
- [ ] **FLOW-06**: 流程末尾的「申请人最终确认」节点自动聚合所有 node_results 渲染汇总邮件

#### 鉴权与深链

- [ ] **AUTH-01**: 邮件 / IM 链接携带 JWT (含 `sub` / `role` / `flow_id` / `node_id` / `jti`)
- [ ] **AUTH-02**: 点击深链 → 前端调 `POST /api/auth/exchange` 用 token 换 HttpOnly Cookie
- [ ] **AUTH-03**: Token 一次性消费 (`jti` 黑名单)，节点状态变更时所有未消费 token 失效
- [ ] **AUTH-04**: Session 与 `flow_id` 绑定，按 `role` 渲染对应视图

#### 通知（双通道）

- [ ] **NOTI-01**: 节点进入 `waiting_human` 时通过 SMTP (QQ 邮箱 smtp.qq.com:465 SSL) 发送邮件
- [ ] **NOTI-02**: 同时通过 Mattermost Bot Personal Access Token 推送 Interactive Message
- [ ] **NOTI-03**: 演示模式 (`APP_MODE=demo`) 下所有邮件路由到 `DEMO_INBOX`，主题前缀加角色标签
- [ ] **NOTI-04**: 通知发送 / 失败 / 重试记录写入 `notifications` 表
- [ ] **NOTI-05**: 节点超时 (>24h) 后台任务扫描自动重发提醒给 assignee + HR

#### LLM 能力点（轻量）

- [ ] **LLM-01**: 接入 GLM API（智谱 AI coding plan），通过 `${GLM_API_KEY}` 环境变量注入
- [ ] **LLM-02**: 在「申请人最终确认」节点用 GLM 对各节点 `result_text` 做一段自然语言摘要，作为汇总邮件正文的开头总结段
- [ ] **LLM-03**: LLM 调用失败 / 超时不阻塞流程，降级为不带摘要的原始版本邮件

#### 演示组织数据

- [ ] **SEED-01**: `scripts/seed_demo_data.py` 通过 Mattermost REST API 创建 5 个 team
- [ ] **SEED-02**: 创建 8 个测试账号（zhang.san / li.si / wang.wu / hr.alice / hr.bob / it.charlie / fin.david / legal.eve），设置 Custom Attributes
- [ ] **SEED-03**: Seed 完成后可一键发起一个 `standard_offboarding` 流程触发首封邮件

#### 前端（多角色 + 一键登录）

- [ ] **WEB-01**: Next.js 15 静态导出 (`output: 'export'`) 由 nginx 直接 serve
- [ ] **WEB-02**: 一键登录入口 `/flow/[flow_id]/node/[node_id]?token=xxx` 自动换 session
- [ ] **WEB-03**: 通用节点处理页（统一表单：节点说明只读 + 详情文本输入必填 + 三态按钮）
- [ ] **WEB-04**: 申请人最终确认页（在通用表单上额外展示节点结果时间线 + GLM 摘要）
- [ ] **WEB-05**: HR Dashboard 总览所有流程，员工 `/my/flows` 查看自己进度

#### 部署

- [ ] **DEPLOY-01**: Docker Compose 编排 postgres / redis / flow-api / nginx
- [ ] **DEPLOY-02**: nginx 反代 `/api/` → flow-api:8000，根路径 serve 前端静态产物
- [ ] **DEPLOY-03**: 一条命令 `docker compose up -d` 在 192.168.2.44 启动全套服务
- [ ] **DEPLOY-04**: `.env.example` 模板覆盖所有必需配置（不含真值）

### Out of Scope

- **与外部业务系统的真实 API 调用**（资产系统 / AD / 财务系统）— v1 不做 Mock 也不做真实集成，节点行为统一为自由文本 + 三态决策；保留 `payload` JSONB 字段供 v2 扩展
- **每个节点差异化的字段 / 表单**（如设备清单的「完好 / 损坏赔偿 / 折旧购买 / 缺失」分类）— 通用表单足够，差异化留到 v2
- **流程模板可视化编排** — v1 流程模板 Python 硬编码，agent-builder 留到 v3
- **节点附件上传** — 留接口不实现
- **节点执行 + 审核两层子流程** — 留模板扩展点，v1 所有节点单层
- **多种离职类型流程**（主动 / 被动 / 协议）— v1 只实现 `standard_offboarding` 一个模板
- **SSO 集成** — 演示用邮件深链一键登录代替；SSO 留到生产化阶段
- **企业微信 / 飞书适配器** — Mattermost 是 v1 主 IM；适配器接口预留，实现留到 v2
- **多语言 / i18n** — 全中文界面
- **移动端适配** — Desktop-first，Mobile 留到后续

## Context

### 已就绪的基础设施

- **Mattermost 实例**：`http://192.168.2.44:8065`（team: `laios`），管理员账号 + Bot Token 可用
- **QQ SMTP 发件邮箱**：`1624456575@qq.com`，授权码已生成（`${QQ_SMTP_AUTH_CODE}` 注入 .env）
- **GLM API**：智谱 AI coding plan，`${GLM_API_KEY}` 注入 .env
- **部署目标**：局域网服务器 `192.168.2.44`（GigaByte laios）
- **远端仓库**：`git@github.com:LaiosOvO/liuxin-interview.git`

### 双层状态模型（关键概念）

本系统有**两份"状态"**，职责互不混淆（详见 PRD §5.3）：

- **LangGraph Checkpoint**（引擎私有）：`PostgresSaver` 自管的 pickle 序列化 state，用于人工中断恢复 / 条件边路由 / 崩溃恢复。**业务侧绝不读这张表**
- **业务状态机记录**（DB 表）：`flow_instances` / `node_states` / `action_logs` / `notifications`，是 source of truth for UI / 审计 / 报表 / 申请人确认聚合

节点函数通过 DB 事务双写两边；崩溃后以业务表为权威重建 LangGraph state。

### 演示场景（面试讲稿）

一位演示者用一个邮箱演完整个流程：
1. 在前端用 `zhang.san` 提交离职申请 → 上级 `li.si` 收到首封邮件
2. 点击邮件按钮 → 浏览器自动以 li.si 身份登录 → 填写审批意见 → 点「继续」
3. HR `hr.alice` 收到下一封邮件 → 同样流程 → 触发并行扇出
4. IT `it.charlie` / Finance `fin.david` / Legal `legal.eve` 三个邮件并行到达，依次处理
5. HR `hr.bob` 终审 → 张三本人收到聚合时间线邮件 → 点确认 → 流程归档
6. 全程 Mattermost 同步推送，可在 IM 直接点按钮（备用通道）

## Constraints

- **部署环境**：仅内网 `192.168.2.44`，无公网域名 / HTTPS 证书；JWT 鉴权可行但绑定本地内网
- **Tech stack 已锁定**：Backend = FastAPI + LangGraph + SQLAlchemy + asyncio + uv；Frontend = Next.js 15 App Router + Tailwind v4 + shadcn/ui + 静态导出
- **包管理**：Backend 用 uv（不接受 poetry / pip-tools），Frontend 用 pnpm
- **Python 版本**：3.12+
- **数据库**：Postgres（业务表 + LangGraph checkpoint 同实例不同 schema）
- **缓存**：Redis（jti 黑名单 + 超时扫描队列）
- **凭证管理**：所有密钥（QQ SMTP / GLM API / Mattermost Bot Token / JWT Secret）只通过 .env 注入，**严禁入库**
- **文档语言**：所有注释 / 文档 / commit message 用中文（用户全局规则 [coding-style.md](~/.claude/rules/common/coding-style.md)）
- **测试覆盖**：≥80%（用户全局规则 [testing.md](~/.claude/rules/common/testing.md)），TDD-first

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Monorepo `backend/` + `frontend/` | 一个 git 仓库 / 一个 docker-compose / 一个 PRD 易于面试讲解 | — Pending |
| Backend uv + pyproject.toml | 2026 主流，极快，与 FastAPI/LangGraph 生态兼容 | — Pending |
| Frontend Next.js 15 静态导出 | nginx 直接 serve 静态文件，无需 Node 运行时容器，部署简单 | — Pending |
| 通用节点结构（自由文本 + 三态） | v1 不做业务系统对接，专注状态机；架构上保留 `payload` 给 v2 扩展 | — Pending |
| 双层状态分离（LangGraph runtime vs 业务表）| 业务可读性 + 跨流程查询 + UI 数据源稳定，与 LangGraph 引擎实现解耦 | — Pending |
| 邮件深链 token 一键登录 | 演示无需 SSO 即可走完闭环；jti 一次性消费防转发滥用 | — Pending |
| 演示模式统一收件箱 + 角色前缀 | 一位演示者一个邮箱演 8 个角色，邮件主题加 `[角色·username]` 区分 | — Pending |
| Mattermost 同时承担「IM 通道」+「轻量 HR 目录」 | 演示阶段免对接真实 HR 系统，user/team/custom-attr 三件套足够 | — Pending |
| 申请人最终确认节点（v0.3 新增）| 让流程的"对申请人闭环"显式化，是状态平台 vs 业务平台分离的最佳例证 | — Pending |
| Phase 1 = Backend 骨架 + LangGraph + Docker 骨架 | 先保证端到端可以 docker compose up 跑起来，再叠通知 / 前端 | — Pending |
| LLM 在 v1 用于「申请人确认邮件的摘要段」一个点 | 演示亮点，但不阻塞核心流程；失败降级到纯文本邮件 | — Pending |
| Mattermost 双通道在 v1 必需 | 与邮件互补提升触达率，演示时同步在 IM 看到推送有"展示效果" | — Pending |

## Reference Documents

- [`PRD.md`](../PRD.md) — 产品需求文档 v0.3（项目实际宪法，本 PROJECT.md 是它的执行视角摘要）
- [`PRD.md §4`](../PRD.md) — 流程 DAG + 通用节点结构 + 申请人最终确认
- [`PRD.md §5.3`](../PRD.md) — 双层状态模型（LangGraph runtime vs 业务表）
- [`PRD.md §6.2`](../PRD.md) — 邮件深链 JWT 一键登录链路
- [`PRD.md §7.4`](../PRD.md) — 演示模式策略
- [`PRD.md §9.1`](../PRD.md) — 测试组织数据 seed
- [`PRD.md §10`](../PRD.md) — Docker Compose + nginx 部署

---
*Last updated: 2026-05-16 after initialization*
