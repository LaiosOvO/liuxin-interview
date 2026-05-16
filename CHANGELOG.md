# Changelog

> 项目：offboarding-flow — AI 驱动的离职流程执行系统
> 格式：基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 1.1.0
> 版本：基于 [SemVer](https://semver.org/lang/zh-CN/)

所有 notable 变更将记录在本文件，按时间倒序排列。
每次实现新功能 / 修复 bug / 重构 / 调整文档结构都会追加到 `[Unreleased]` 节，正式发布版本时再切到对应版本号。

---

## [Unreleased]

### Added (Phase 2)

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
