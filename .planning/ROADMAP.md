# Roadmap: offboarding-flow

**Created:** 2026-05-16
**Total Phases:** 6
**Estimated Duration:** ~18-22 工作日（3-4 周交付）
**Approach:** 单进程 monolith，每个 phase 完成后系统都能 `docker compose up` 端到端演示

> 本 roadmap 由 `.planning/research/SUMMARY.md` §Implications for Roadmap 合成而来；4 份研究（STACK / FEATURES / ARCHITECTURE / PITFALLS）已一致背书 6 phase 拆分。

---

## Phase Overview

| # | Phase | Goal | REQ-IDs | Duration | Success Criteria | Risk |
|---|-------|------|---------|----------|------------------|------|
| 1 | **基建 + LangGraph 骨架** | 状态机引擎 + checkpoint + 业务表 schema + 最小 2 节点跑通；Docker 编排骨架 | FLOW-01/03, DEPLOY-01/04/05 | 3-4 天 | uvicorn 启动 → POST /api/flows 起流程 → POST advance 推进 → docker restart 后能从 interrupt 恢复 | LOW（HIGH confidence + 完整代码模板） |
| 2 | **双写规范 + 节点完整化 + 申请人确认** | 业务事务 commit → graph.invoke 双写规范；10 节点全部实现 + 并行 fan-out；申请人最终确认节点 | FLOW-02/04/05/06 | 3-4 天 | 跑到任意节点故意 invoke 失败 → action_log.failed → recover 脚本可重试；申请人邮件聚合显示全 10 节点结果 | MEDIUM（双写一致性 + 幂等是项目最深的设计） |
| 3 | **鉴权 + 深链 JWT 一键登录** | JWT 签发 + jti 一次性消费 + token→session 交换 + 按 role 渲染 | AUTH-01/02/03/04 | 2-3 天 | `asyncio.gather(exchange, exchange)` 并发同一 token 必须只有一个 200；跨角色 token 立即拒绝 | LOW（HIGH confidence + Redis SET NX EX 已成熟） |
| 4 | **通知 + Bot 入口 + AI 增强 + Seed + 逾期模拟**（v0.4 大幅扩展）| outbox 异步通知 + QQ SMTP + Mattermost Bot 双向（入站 webhook + 出站推送）+ seed 演示数据 + GLM 摘要 + AI 推理下一步 + AI 后台报告 + AI 边界声明 + 逾期/证据缺失模拟 | NOTI-01/02/03/04, **LLM-01~06**, **BOT-01~04**, **TIMEOUT-02/03**, SEED-01/02/03 | 6-8 天 | 在 Mattermost `@offboarding-bot start zhang.san` 立即收到 10 节点状态报告；`report <flow_id>` 输出 AI 分析含阻塞事项；`simulate-timeout` 立即触发逾期；curl 起流程 → 10s 内 QQ 邮箱收到带角色前缀邮件；seed 跑两次 0 错误 | MEDIUM-HIGH（Mattermost 入站 webhook + GLM API + 多触发场景）|
| 4.5 | **加分项：自动动作节点演示（v0.4 新增）** | 新增 AutoNode 类型 + 演示 `auto_archive_to_storage` 节点调 mock HTTP API；docker-compose 加 mock-archive-service | AUTO-01/02/03 | 1 天 | 流程跑到 archive 前会自动调用 mock 服务把 node_results 写入文件；Mattermost 看到"自动执行"消息；演示话术清楚说明为什么其他节点不能自动化 | LOW（架构已支持，只需加节点类型 + mock service） |
| 5 | **前端 Next.js + 多角色 + 申请人时间线 + 逾期标签** | 一键登录页 / 通用节点表单 / HR Dashboard（含 AI 报告按钮）/ 申请人最终确认页 / 逾期 + 证据缺失标签 | WEB-01/02/03/04/05, **TIMEOUT-04** | 4-5 天 | `pnpm build` 0 error；客户端路由刷新不 404；邮件点击→自动登录→看到对应角色页面→提交决策→流程推进；HR Dashboard 节点旁正确显示 `⚠️ 证据待补充` / `⏰ 已超时` 标签 | MEDIUM（Next.js 15 静态导出 + Tailwind v4 是 2026 新栈） |
| 6 | **部署 + 演示模式切换 + 超时扫描 + 运维脚本 + 演示打磨** | Dockerfile + nginx.conf + entrypoint.sh + APScheduler timeout_scan + 演示 runbook | DEPLOY-02/03, NOTI-05 | 2-3 天 | `docker compose up -d` 在 192.168.2.44 一键启动；E2E 演示通过；"Looks Done But Isn't" Checklist 全过 | LOW（HIGH confidence + 完整模板） |
| 8 | **IM/Doc 全抽象 + Huly 接入 + 流程 MCP 化** | 8A IMListener + dispatch_message 抽象重构；8B Huly Provider（Node sidecar + service token）+ 同步业务 DB 13 用户到 Huly；8C 流程节点 MCP server | ABS-01..05, HULY-01..09, MCP-01..06 | 16 天 / 3-4 周 | `.env` 改 `IM_PROVIDER=huly` 业务代码零改动；it.charlie 在 Huly DM 说"我要离职"启流程；Claude Desktop 配 MCP 后能 `get_flow` 返回 DAG | MEDIUM（多语言栈：Node sidecar + Python provider；详见 [PRD-Phase-8.md](../PRD-Phase-8.md)） |

### Phase 8 进度（2026-05-17）

| Plan | 内容 | REQ-IDs | 状态 |
|------|------|---------|------|
| 8-01 | IM 抽象层 + DocProvider/IMProvider 完善 + HandlerRegistry | ABS-01..05 | ✓ Complete (5 commits b27eb2d..c358edc) |
| 8-02 | ABS-06 节点元数据外提到 config/nodes.yaml | ABS-06 | ○ Pending |
| 8-03 | Huly 镜像 pull 脚本 + docker-compose huly-stack/huly profile + .env.example HULY_* + 11 集成测试 | HULY-01..02 | ✓ Complete (2 commits 51183c6..fa8b427) |
| 8-04 | huly-bridge sidecar 骨架（backend/sidecars/huly-bridge/ — Express + tsx + Dockerfile + service token + /healthz + 52 单测） | HULY-03..04 | ✓ Complete (5 commits d070cea..a9992a3) |
| 8-05 | sidecar IM/Doc 业务路由真实现 + listener 反向订阅 + Python HulyIMProvider/HulyDocProvider + HulyListener + POST /api/internal/huly/event 路由 + factory + main lifespan + 73 测试 | HULY-05..07 | ✓ Complete (3 commits 08534c9..2588243) |
| 8-06 | seed_huly_users + Plan 05 端到端 E2E（browser webapp-testing） | HULY-08 | ○ Pending |
| 8-07 | 流程节点 MCP server | MCP-01..02 | ○ Pending |

**总计**：21-26 工作日（v0.4 增量），**45 个 v1 requirements 100% 覆盖**（v0.3 base 31 + v0.4 增 14：AI 增强 6 + Bot 入口 4 + 逾期 4，含加分项）。Phase 8 是 v0.5 新增（16 天）。

**面试评分点对齐**：评分点 1-9（含加分项）+ Mattermost @bot 简化入口均映射到对应 phase，详见 [REQUIREMENTS.md 评分对照表](./REQUIREMENTS.md#面试评分点对照)。

---

## Phase Details

### Phase 1: 基建 + LangGraph 骨架 + 业务表 schema

**Goal:** 把状态机引擎、checkpoint 持久化、业务表 schema、Docker 编排基座一次性搭起来，跑通最小 2 节点流程（apply + manager_review），是所有后续 phase 的依赖。

**Requirements (5):**
- FLOW-01: LangGraph StateGraph 框架就位（2 个节点）
- FLOW-03: AsyncPostgresSaver checkpoint 持久化
- DEPLOY-01: Docker Compose postgres/redis 起来 + 双 schema 隔离
- DEPLOY-04: `.env.example` + `.gitignore` + pre-commit gitleaks
- DEPLOY-05: alembic + saver.setup 启动顺序

**Success Criteria:**
1. uvicorn 启动后 `/api/health` 返回 200
2. `POST /api/flows {"employee_id": "zhang.san"}` 创建流程实例
3. `POST /api/flows/{id}/nodes/{nid}/actions {"action": "advance", "result_text": "...", "actor": "..."}` 推进到下一节点
4. `docker compose restart flow-api` 后流程进度无丢失（从 interrupt 恢复）
5. 业务表 `flow_instances` / `node_states` / `action_logs` 与 LangGraph checkpoint 表数据一致

**Key Implementation Notes** (SUMMARY §Phase 1):
- uv 项目骨架 + Pydantic Settings + pre-commit gitleaks（**第一个 commit 之前必有**, PITFALLS #8）
- 双 schema：业务 `app` + LangGraph `langgraph`，`search_path` 隔离
- `OffboardingState` TypedDict + `Annotated[list, operator.add]` reducer（漏 reducer 是 Pitfall #4）
- 动态 `interrupt()` + `Command(resume=...)`，**不要用 `interrupt_before`** (R3)
- pytest fixture `loop_scope=session`
- `flow_id` 强制 uuid4()

**Out of Scope (this phase):**
- 鉴权（Phase 3）
- 通知（Phase 4）
- 前端（Phase 5）
- 其他 8 个节点（Phase 2）

---

### Phase 2: 业务表双写规范 + 节点函数完整化 + 申请人最终确认节点

**Goal:** 落实"业务事务 commit → graph.ainvoke 双写"核心契约；把 10 个节点全部实现 + 并行 fan-out/fan-in；做出项目最值得讲的 `applicant_final_confirm` 节点（DF-02 ★★★★★）。

**Requirements (4):**
- FLOW-02: 节点函数双写业务表 + 事务边界
- FLOW-04: 通用节点结构（自由文本 + 三态决策）
- FLOW-05: 退回路径 + 拒绝终止
- FLOW-06: 申请人最终确认节点 + node_results 聚合

**Success Criteria:**
1. 跑到任意节点故意让 graph.invoke 抛异常 → `action_logs.status='failed'` 可见 → `scripts/recover_from_db.py` 可手动重试
2. 申请人最终确认节点的汇总邮件显示完整 10 节点结果时间线（含 actor / completed_at / result_text）
3. 退回路径正确：HR 初审退回 → apply；申请人确认退回 → hr_final
4. 拒绝路径正确：manager_review 拒绝 → 流程终止；hr_final 拒绝 → 流程终止
5. 5 个并行节点（device_return / access_revoke / knowledge_handover / finance_settle / legal_sign）全部完成才进入 hr_final

**Key Implementation Notes** (SUMMARY §Phase 2):
- 节点函数 `is_first_entry` 判断 + 所有 INSERT 用 upsert（**幂等是硬约束**，interrupt 抛 GraphInterrupt 会重试节点函数）
- `node_service.submit_action` 顺序：业务事务 commit → graph.ainvoke(Command) → 失败 mark action_log.failed
- `context.node_results[]` 追加（Annotated reducer）累计执行结果
- `scripts/recover_from_db.py` 工具：从业务表重建 LangGraph state

**Out of Scope (this phase):**
- 鉴权（Phase 3 才接）
- 通知发送（节点函数现在只写业务表，暂不发邮件）
- LLM 摘要（Phase 4 才接）

---

### Phase 3: 鉴权 + 深链 JWT 一键登录 + jti 一次性消费

**Goal:** 落地"邮件链接点击即登录"的核心机制。通知里要带 token 链接，所以鉴权必须在 Phase 4 通知之前就绪。

**Requirements (4):**
- AUTH-01: JWT 签发 + payload schema
- AUTH-02: `/api/auth/exchange` token → session cookie
- AUTH-03: jti 一次性消费（Redis SET NX EX）
- AUTH-04: 三元组绑定 + role 校验

**Success Criteria:**
1. `asyncio.gather(exchange(token), exchange(token))` 并发同一 token 只有一个返回 200，另一个 401
2. 不同 role 用同一 token 访问其他 role 视图：立即 401
3. 节点状态 advance 后，该 node 所有未消费 token 立即失效
4. Token 过期后 exchange 返回 401（exp 严格校验）
5. 跨 flow_id 复用 token 立即拒绝

**Key Implementation Notes** (SUMMARY §Phase 3):
- pyjwt[crypto] HS256（**不用 python-jose**）
- Redis `SET ... NX EX TTL` 原子操作 — 防止双击 race（PITFALLS #6）
- HttpOnly Cookie + `SameSite=Lax`（不能 Strict，否则邮件链接跳转后 cookie 不发）
- `secure=(APP_MODE=="prod" and HTTPS_ENABLED)` — 内网 HTTP 不能开 Secure
- **R2 必须敲定**：深链 URL 格式 = query string（`/flow/handle?flow_id=...&node_id=...&token=...`）— 这决定 P5 实现路径

**Out of Scope (this phase):**
- 通知里塞 token（Phase 4）
- 前端登录页（Phase 5）

---

### Phase 4: 通知双通道 outbox + Seed 脚本 + LLM 摘要降级

**Goal:** 把"消息能到达 + 演示数据准备 + LLM 加分项"作为一个完整的 phase 交付。鉴权打通后通知里能塞 token；申请人节点 Phase 2 已就绪，LLM 摘要是末端可选增强。

**Requirements (9):**
- NOTI-01/02/03/04: 邮件 + Mattermost outbox 异步通知
- LLM-01/02/03: GLM 接入 + 申请人邮件摘要 + 失败降级
- SEED-01/02/03: 演示组织数据 seed

**Success Criteria:**
1. `curl POST /api/flows` 起流程 → 10 秒内 QQ 邮箱 `1624456575@qq.com` 收到带角色前缀的邮件（如 `[上级·li.si] 离职流程 — 张三 — 上级审批待处理`）
2. 邮件中文 subject 正确显示（RFC 2047 编码不乱码）
3. 邮件 HTML 在 QQ 邮箱客户端 + Apple Mail 正常显示按钮
4. Mattermost 同时收到 Interactive Message 卡片（点按钮跳深链）
5. 故意把 `GLM_API_KEY` 设错 → 申请人邮件无 GLM 摘要但能发出（降级生效）
6. `python scripts/seed_demo_data.py` 跑两次 0 错误（幂等）
7. 8 个测试账号 + 5 个 team + Custom Attributes 在 Mattermost 后台可见
8. `notification_outbox` 表中 pending 记录在 10 秒内被 drain
9. 故意把 QQ SMTP 密码设错 → outbox 表中 status=failed + 节流后自动重试 3 次

**Key Implementation Notes** (SUMMARY §Phase 4):
- **outbox 模式**：节点函数事务内 `INSERT INTO notification_outbox`，APScheduler `outbox_drain` 每 10s drain — 避免 QQ SMTP 5-10s 卡顿阻塞 graph (R5)
- `EmailEnvelope` 演示 vs 生产差异；`APP_MODE=demo` 主题加前缀 + 正文加横幅 (PITFALLS #10)
- 中文 subject 用 `EmailMessage` 自动 RFC 2047 编码
- HTML 邮件 table-based 模板（兼容老邮件客户端）
- Mattermost `AllowedUntrustedInternalConnections` 配置 + seed 校验（PITFALLS #7）
- GLM 用 `openai` 包指向智谱 base_url；`asyncio.timeout(8)` 超时
- seed 脚本 `ensure_user/ensure_team` 用 GET-then-create 模式

**Out of Scope (this phase):**
- 超时扫描 timeout_scan（Phase 6 落地）
- Mattermost Interactive Message callback 接收（v1 只做跳转 URL，v2 才接 callback）

---

### Phase 5: 前端 Next.js + 多角色 + 申请人时间线 + HR Dashboard

**Goal:** 完成"点 → 登录 → 决策"的前端闭环。基于研究推荐的现成模板加速开发。

**Requirements (5):**
- WEB-01: Next.js 15 静态导出基座
- WEB-02: 一键登录入口 `/flow/handle?...`
- WEB-03: 通用节点处理页 NodeForm
- WEB-04: 申请人最终确认页 + 时间线 + GLM 摘要段
- WEB-05: HR Dashboard + 员工 /my/flows

**Success Criteria:**
1. `pnpm install && pnpm build` 0 error
2. `pnpm preview` 或 nginx serve `out/` 后访问 `http://localhost/flow/handle?...&token=...` 自动换 session 并跳转到对应 role 视图
3. 三态按钮颜色区分（继续=蓝 / 退回=黄 / 拒绝=红），点击有 confirm dialog
4. 申请人确认页时间线正确显示 10 节点结果（GLM 摘要段在顶部）
5. HR Dashboard 表格支持状态过滤 / 搜索 / 分页 / "重发通知"按钮
6. 客户端路由刷新不 404（nginx `try_files /index.html` 兜底）
7. 全程演示：邮件点击 → 自动登录 → 看到正确视图 → 提交决策 → 浏览器看到下一节点状态

**Key Implementation Notes** (SUMMARY §Phase 5 + FRONTEND_REFERENCES.md):
- **骨架 fork**：`Kiranism/next-shadcn-dashboard-starter` (6.4k★ MIT) — 把 next 版本降到 15.x，删掉 Clerk/Sentry
- **工单页布局**：从 `satnaing/shadcn-admin` 的 `src/features/chats/index.tsx` 拷贝双栏布局（左列表 + 右详情）
- **节点表单 / 时间线 / 一键登录中转页**：用 shadcn `Card` + `Separator` 自写，30-50 行即可（找轮子比写还慢）
- 所有页面 `'use client'`（Next.js 静态导出 + Server Components 在 export 模式下有限制）
- 深链格式 query string：`app/flow/handle/page.tsx` 单一壳页面 + `useSearchParams`（规避 issue #79380）
- SWR 数据拉取 + react-hook-form + zod 校验

**Out of Scope (this phase):**
- 状态机 DAG 可视化（v2）
- 移动端响应式（v2）

---

### Phase 6: 部署 + 演示模式切换 + 超时扫描 + 运维脚本 + 演示打磨

**Goal:** 把开发期搭起来的所有部分打包成 Docker 一键起，完成 192.168.2.44 真实部署，写演示 runbook 和讲稿，做"演示前一票否决" checklist 验证。

**Requirements (3):**
- NOTI-05: APScheduler timeout_scan 每分钟扫超时
- DEPLOY-02: nginx 反代完整配置
- DEPLOY-03: docker compose 一键起 + APP_MODE 启动 log 校验

**Success Criteria:**
1. 在 192.168.2.44 执行 `docker compose up -d` 全部服务起来无 error
2. `curl http://192.168.2.44/api/health` 返回 200
3. `curl -I http://192.168.2.44/` 返回 200 + Content-Type text/html
4. 演示者从浏览器打开 `http://192.168.2.44`，用 zhang.san 起流程，全程走完 10 节点（8 邮件 + 8 Mattermost 推送）
5. 故意 24+ 小时不处理某个节点 → APScheduler timeout_scan 自动重发提醒邮件
6. `dev-reset.sh` 有二次确认 + 备份 postgres 数据
7. 启动 log 显式打印 `APP_MODE=demo`；前端 footer 显示 mode
8. "Looks Done But Isn't" Checklist 全过（演示前 18 项必检）

**Key Implementation Notes** (SUMMARY §Phase 6 + PITFALLS deploy 类):
- 后端 Dockerfile 多阶段（uv builder + python:3.12-slim-bookworm runtime）
- nginx.conf: `location ^~ /api/` 优先级修饰符 + `try_files /index.html` 兜底 + `log_format` 不记录 query string（防 token 泄露 PITFALLS #13）
- entrypoint.sh: `alembic upgrade head` → `await checkpointer.setup()` → `uvicorn`
- `extra_hosts: host-gateway` 让容器访问宿主机 Mattermost :8065（PITFALLS #21）
- **修正 R1**：`DEEPLINK_BASE_URL=http://192.168.2.44`（不带 :3000）
- APScheduler `timeout_scan` job：每 60s 扫 `node_states where status='waiting_human' and entered_at < now()-24h` → 重发提醒
- 运维脚本：`dev-restart.sh` / `dev-reset.sh`（二次确认 + 备份）/ `cleanup_old_checkpoints.py`
- 演示 runbook：reset → seed → 起流程 → 演示话术 → 截图 / 录屏脚本

**Out of Scope (this phase):**
- 生产化 HTTPS / SSO / RBAC（v2）
- 多 worker 部署 + leader lock（v2）

---

## Phase Dependencies

```
Phase 1 (骨架)
   ↓
Phase 2 (双写 + 申请人确认)
   ↓
Phase 3 (鉴权)       ← 通知需带 token，故先于 Phase 4
   ↓
Phase 4 (通知 + Seed + LLM)
   ↓
Phase 5 (前端)       ← 必须有真实邮件能点，故后于 Phase 4
   ↓
Phase 6 (部署 + 打磨)
```

**关键 sequencing 决策**（来自 SUMMARY §Phase Ordering Rationale）：
- P3 鉴权必须先于 P4 通知（通知里要带 token 链接）
- P5 前端必须后于 P4 通知（必须先有真实邮件能点）
- P2 申请人确认必须先于 P4 LLM（节点框架先就绪，LLM 是末端可选增强）
- 并行节点放在 P2 而不是更早（单线流程先打通再加并行复杂度）
- Docker 完整部署放最后（开发期本地迭代快）

---

## Risk Management

| Risk | Severity | Phase | Mitigation |
|------|----------|-------|------------|
| LangGraph 双写不一致 | **HIGH** | P2 | ARCHITECTURE §3 Pattern 1 给出双写时序代码 + 失败 mark action_log.failed + recover 脚本 |
| interrupt 重跑副作用不幂等 | **HIGH** | P2 | 节点函数 `is_first_entry` + 所有 INSERT upsert + outbox UNIQUE 约束 |
| JWT 双击 race condition | HIGH | P3 | Redis `SET NX EX` 原子操作（已有成熟模式） |
| Mattermost callback 防火墙 | HIGH | P4 | `AllowedUntrustedInternalConnections` 配置 + seed 启动校验 |
| 凭证泄露 / 演示模式上线 | HIGH | P1 + P6 | 第一个 commit 之前必有 `.gitignore` + pre-commit gitleaks；启动 log 显式打印 mode |
| Next.js 静态导出 + 动态路由 | MEDIUM | P5 | **R2 采纳方案 A**（query string），规避 issue #79380 |
| QQ SMTP 频率限制 | MEDIUM | P4 | outbox 节流 + 失败 3 次重试 + alert |
| GLM API 不兼容 OpenAI 包 | LOW | P4 | 启动前 30 分钟 POC 验证；不通则降级 zhipuai SDK |
| pnpm 11 + Node 22 漂移 | LOW | P5 | `packageManager: "pnpm@11.1.1"` 锁定 |

---

## PRD Revisions Required Before Implementation

> SUMMARY §5 列出的 6 处必修订项，**Phase 1 启动前**完成 PRD v0.3 → v0.4 升级：

| # | PRD 位置 | 修订 | 严重度 |
|---|---------|------|-------|
| R1 | §10.1 DEEPLINK_BASE_URL | 去掉 :3000 | 致命 |
| R2 | §6.2 / §10.0.1 深链格式 | 改 query string 方案 A | 致命 |
| R3 | §8.1 LangGraph API | 改 dynamic interrupt() + Command(resume) | 致命 |
| R4 | §10 部署 | 明确 alembic + saver.setup 分工 + 双 schema | 改进 |
| R5 | §10 / §5.3.1 通知 | 改 outbox 模式 | 改进 |
| R6 | §10 部署 | 锁 Node 22 LTS + pnpm 11.1.1 | 改进 |

**建议**：在 Phase 1 启动前先做一次 PRD v0.4 修订 commit，把这 6 处一次性改完，避免 implementation 时反复同步文档。

---

## Milestone Mapping (与 PRD §13 对齐)

| PRD M | GSD Phase | 内容 |
|-------|-----------|------|
| M0 PRD | （已完成） | PRD v0.3 已写完 |
| M1 设计 | （已完成） | `.planning/research/*` 4 维度调研 + SUMMARY |
| M2 核心后端 | Phase 1 + 2 | LangGraph 状态机 + 双写规范 + 申请人确认 |
| M3 通知 | Phase 3 + 4 | 鉴权 + 邮件 + Mattermost + Seed + LLM |
| M4 前端 | Phase 5 | Next.js 多角色 Dashboard |
| M5 集成 | （v2 才做）| 与真实业务系统对接 |
| M6 演示 | Phase 6 | 部署 + runbook + 录屏 |

---

*Roadmap created: 2026-05-16*
*Source: synthesized from .planning/research/SUMMARY.md + REQUIREMENTS.md + PROJECT.md + PRD.md v0.3*
*Last updated: 2026-05-16 after creation*
