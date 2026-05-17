# Project State: offboarding-flow

## Project Reference

See: [.planning/PROJECT.md](./PROJECT.md) (updated 2026-05-16)

**Core value:** 让"流程状态机"端到端可见且可驱动 — 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进直到申请人最终确认
**Current focus:** Phase 8 IM/Doc 全抽象 + Huly 接入 — Plan 06 (Huly seed + 部署 runbook) **已完成**；Phase 8B Huly 接入完整闭环；下一步 Plan 02（节点元数据外提）/ Plan 07（MCP server）

---

## Current Status

**Stage:** Phase 8 Plan 06 完成 — sidecar admin API（双 token 鉴权 + 走 admin login → createInvite → signUpJoin 避开 Pitfall #1）+ scripts/seed_huly_users.py（业务 DB 13 用户幂等同步）+ .env.example 完整 14 HULY_* 段 + README §9 八子段部署 runbook + Playwright E2E spec scaffold + 18 新测试全 PASS + 0 回归（HULY-08/09 2 REQ Complete）

**Last completed:**
- Phase 8 Plan 06: sidecar admin.ts + seed_huly_users.py + seed_huly_workspace.py + tests + README §9 runbook + E2E spec/报告 scaffold（3 commits a39ec41..5539cb8）— HULY-08/09 2 REQ Complete；Phase 8B Huly 接入实质闭环（仅 E2E 截图填补待真环境）
- Phase 8 Plan 05: sidecar 3 模块（im.ts/doc.ts/listener.ts）+ Python 4 模块（HulyIMProvider/HulyDocProvider/HulyListener/api/internal_huly）+ factory + main.py 装配（3 commits 08534c9..2588243）— HULY-05/06/07 3 个 REQ Complete；IM_PROVIDER=huly DOC_PROVIDER=huly 一行切换可用
- Phase 8 Plan 04: backend/sidecars/huly-bridge/ 完整 17 文件 + 52 vitest 单测 PASS + Dockerfile build + run + curl 全通（5 commits d070cea..a9992a3）— HULY-03/04 2 个 REQ Complete
- Phase 8 Plan 03: scripts/pull_huly_images.sh + docker-compose.yml huly-stack/huly profile + .env.example HULY_* + 11 个集成测试（2 commits 51183c6..fa8b427）— HULY-01/02 2 个 REQ Complete
- Phase 8 Plan 01: IMListener Protocol + dispatch_message + DocProvider 3 新 lifecycle 方法 + IMProvider register hook + BotHandlerRegistry（5 commits b27eb2d..c358edc）— ABS-01..05 5 个 REQ Complete
- Phase 7+ (2026-05-17): 协作文档抽象 + 按员工分文件夹 + 生产级 DAG + 完整 E2E（commit 51b1062）
- Phase 2-6 + 4.5: 全部历史 phase 已 merge main

**Next action:** Phase 8 剩余 plan（无阻塞，可并行）：
- Plan 02 (ABS-06 节点元数据外提到 config/nodes.yaml) — 与本 plan 无依赖
- Plan 07 (MCP server + AI 节点增强 — 复用 HandlerRegistry 暴露 11 命令为 MCP tools) — 独立 wave，可立即开始
- E2E 截图填补（orchestrator 启 huly-stack 后 8 步完成）— scaffold 已就绪

---

## Roadmap Summary

| # | Phase | Status |
|---|-------|--------|
| 1 | 基建 + LangGraph 骨架 | ✓ Complete |
| 2 | 双写规范 + 节点完整化 + 申请人确认 | ✓ Complete |
| 3 | 鉴权 + 深链 JWT 一键登录 | ✓ Complete |
| 4 | 通知 + Bot 入口 + AI 增强 + Seed + 逾期模拟 | ✓ Complete |
| 4.5 | 加分项：自动动作节点演示 | ✓ Complete |
| 5 | 前端 Next.js + 多角色 + 申请人时间线 + 逾期标签 | ✓ Complete |
| 6 | 部署 + 演示模式切换 + 超时扫描 + 运维脚本 + 演示打磨 | ✓ Complete |
| 7 | 协作文档抽象 + 按员工分文件夹 + 生产级 DAG + E2E | ✓ Complete |
| 8 | IM/Doc 全抽象 + Huly 接入 + 流程 MCP 化 | ◐ In Progress（Plan 01 ✓ + Plan 03 ✓ + Plan 04 ✓ + Plan 05 ✓ + Plan 06 ✓；Phase 8B Huly 接入完整闭环；Plan 02 / 07 待执行）|

详见 [.planning/ROADMAP.md](./ROADMAP.md)。

---

## Recent Sessions

| Date | Stage | What happened |
|------|-------|---------------|
| 2026-05-16 | Init | PROJECT.md + config.json + 4 个并行研究 agent 完成 + SUMMARY 合成 + FRONTEND_REFERENCES 调研 + REQUIREMENTS + ROADMAP 落盘 |
| 2026-05-16 | Init | PRD v0.4 大幅扩展（对齐面试 9 项评分点 + Mattermost @bot 入口 + AI 增强）+ REQUIREMENTS 扩到 45 个 REQ + ROADMAP 加 Phase 4.5 加分项 |
| 2026-05-16 | discuss-phase 1 | CONTEXT.md 落盘（auto 模式 + 用户即时约束：psql 数据库 + 部署 192.168.2.44）+ CLAUDE.md 创建（并行开发 + browser-harness E2E 约定）|
| 2026-05-16 | plan-phase 1 --auto | 7 个 plan 落盘（3 个 wave）+ 全部执行（35 测试通过 + 4 API 端点 + LangGraph 骨架 + Docker 编排）+ commit `bf20b03`(代码) + `29b657d`(docs) |
| 2026-05-16 | plan-phase 2 --auto (worktree) | 6 个 plan 落盘（4 个 wave）+ 全部执行（126 测试通过 + 双写规范完整 + 10 节点 + 申请人确认 + recover CLI）+ commits 9c113cb..326ffd8 + merged main |
| 2026-05-16 | plan-phase 3 --auto (worktree) | 4 个 plan 落盘（3 个 wave）+ 全部执行（73 测试通过 + auth/ 11 模块 + POST /api/auth/exchange + node 状态变更 hook）+ commits 609c139..16ce4db + merged main |
| 2026-05-16 | plan-phase 4.5 --auto (worktree) | 3 plan 落盘 + 全部执行（AutoNode + mock-archive-service + httpx tenacity + 三层测试 38 用例 pass）— REQ AUTO-01/02/03 Complete；与 Phase 4 worktree 并行无冲突；演示话术 PRD §18.3 固化到 CHANGELOG |
| 2026-05-17 | Phase 7+ (single commit 51b1062) | 协作文档抽象（DocProvider/IMProvider Protocol + 5 实现）+ 按员工分文件夹 + 生产级 DAG + AI 节点交接 + 完整 E2E（it.charlie + xiao.fang） |
| 2026-05-17 | plan-phase 8/01..07 落盘 | Phase 8 拆 7 plan（ABS / Huly / MCP 三件套）— PRD-Phase-8 + 设计 docs 一并入库；08-01 / 08-02 / 08-03 / 08-04 / 08-05 / 08-06 / 08-07 PLAN.md 全部 ready |
| 2026-05-17 | execute-plan 08-01 (resume) | Plan 01 (IM/Doc 抽象 + HandlerRegistry) 完成 — 前一次 executor 完 task 01-01/02/03（commits b27eb2d / 6db4968 / 9064c3a）；本次 executor 继续完成 01-04..01-08（commits 3d4abd0 / c358edc + 最终 metadata commit）— 58 个新单测全 PASS + 新代码 100% 覆盖率 + ABS-01..05 5 个 REQ 全部 Complete + 0 回归 |
| 2026-05-17 | execute-plan 08-03 --auto | Plan 03 (Huly Docker stack + profile) 完成 — 2 commits (51183c6 feat HULY-01 scripts + docs / fa8b427 feat HULY-02 compose + .env + 11 tests)；15 镜像清单（11 业务 + 4 基础设施，对齐上游 huly-selfhost v0.7.423）+ huly-stack/huly 两 profile + 默认 0 影响现有 6 service + 11 集成测试 PASS + gitleaks 通过；HULY-01/02 2 REQ Complete |
| 2026-05-17 | execute-plan 08-04 --auto | Plan 04 (huly-bridge Node sidecar 骨架) 完成 — 5 commits (d070cea init / cd4085f core / 3b1bb6f entrypoint / 1a69525 tests / a9992a3 CJS fix)；17 文件 ~1700 LOC（Express + tsx + vitest + Dockerfile）+ Huly service token 生成（generateToken systemAccountUuid + service='offboarding-bot' 已源码验证 + Docker 真启动 smoke 验证）+ /healthz 反映 Huly 连接 + 7 业务路由 stub + 52 单测 PASS（auth+config 100% coverage）+ tsc 0 error；4 deviations 自动修复（document 包 npm 缺 0.7.423 / @hcengineering 缺 .d.ts / CJS ESM interop / 测试套件扩展）；HULY-03/04 2 REQ Complete |
| 2026-05-17 | execute-plan 08-05 --auto | Plan 05 (Huly 业务接入层 + 反向通道) 完成 — 3 commits (08534c9 sidecar IM 路由 / 5114e45 sidecar Doc+listener+index / 2588243 Python provider+listener+route)；16 创建 + 7 修改 ~3400 LOC（sidecar im.ts/doc.ts/listener.ts + Python HulyIMProvider/HulyDocProvider/HulyListener/api/internal_huly + factory + main lifespan）；73 测试 PASS（38 vitest + 35 pytest）+ tsc 0 error + mypy 0 error + ruff 0 error；4 deviations 自动修复（healthz mock 补 / mypy 类型注解 / BRIDGE_TOKEN 空时主动 401 安全 / tests/unit/workers 包入口）；HULY-05/06/07 3 REQ Complete；IM_PROVIDER=huly DOC_PROVIDER=huly 一行切换可用 |
| 2026-05-17 | execute-plan 08-06 --auto | Plan 06 (Huly seed + 部署 runbook + E2E scaffold) 完成 — 3 commits (a39ec41 sidecar admin + 配置 + workspace 探测 / c2c6b97 seed_huly_users + 集成测试 + README §9 / 5539cb8 Playwright E2E spec + 报告 scaffold)；8 创建 + 11 修改 ~2400 LOC（sidecar admin.ts + Python scripts + tests + E2E spec + 文档）；18 新测试 PASS（12 sidecar vitest admin + 6 backend pytest seed）+ tsc 0 + mypy 0 + ruff 0；4 deviations 自动处理（listener test 字段补 / httpx import 提升 / mypy stub ignore / auto-mode checkpoint scaffold）；HULY-08/09 2 REQ Complete；Phase 8B Huly 接入完整闭环（admin login → createInvite → signUpJoin 避开 Pitfall #1 + 双 token 鉴权 + .env 14 HULY_ 段 + README §9 八子段 runbook） |

---

## Plan 06 Decisions (2026-05-17)

- **走 admin login + 普通 createInvite + anonymous signUpJoin 避开 Pitfall #1** — createInviteLink(autoJoin=true) 仅 service=schedule 放行（源码定位 verifyAllowedServices）；用 admin token 调普通 createInvite + 公开 signUpJoin 一步完成
- **双 token 鉴权（BRIDGE_TOKEN + ADMIN_TOKEN）** — BRIDGE 是业务通用，ADMIN 是 admin 路由专用二级保护；防 LLM 通过 BRIDGE 调 admin 路由污染 Huly 账号数据；timing-attack 同 bridgeAuth 防御
- **admin token 缓存 5 min TTL** — 平衡 login 开销与 token 时效；sidecar 重启即失效不需持久化
- **幂等兜底 = signUpJoin 失败 → login fallback** — 检测 already exists keyword → login 拿 accountUuid → 200 skipped=true；login 失败 → 409 ACCOUNT_EXISTS_PASSWORD_MISMATCH 提示密码不一致
- **_setTestAccountClientFactory 测试注入** — 不通过 vi.mock 替换整模块，注入 factory function；每用例独立 ctrl 更可读
- **seed 集成测试 monkeypatch _load_users_from_db** — 主验证语义在 sidecar HTTP（不在 DB 读取）；CI 无 PG 时仍可跑（CLAUDE.md §2.3 折中），真 DB 路径在实际 seed + E2E 验证
- **seed_huly_workspace 不强制 createWorkspace** — plan 明示避免范围爆炸；通过 sidecar /healthz 探测 huly_connected 即视为 workspace 就绪
- **scripts/* 直接 import 而非 cli 模块** — 复用现有 scripts/seed_demo_data.py 模式；测试用 sys.path.insert + 模块名导入
- **README §9 完整 runbook（8 子段）** — 配置 → 启 sidecar → seed → 切换 → 验证 → 回滚 → 安全建议；含真实命令 + dry-run + 重跑幂等示例
- **Playwright spec isHulyUp() skip 防御** — 无 Huly 环境时自动 skip（不阻 CI）；真实跑通需 orchestrator 启 huly-stack 后手动执行
- **E2E 截图填补由 orchestrator 后续** — Task 3 是 checkpoint:human-verify，auto 模式下完成 spec + 报告 + selector 适配点 + tool 调用链路图 scaffold，截图填补待真环境

---

## Plan 05 Decisions (2026-05-17)

- **socialKey 模式作为身份解析 canonical** — 与 ai-bot/utils/platform.ts:getAccountBySocialKey 同模式（SocialIdentity.key='email:{user}@demo.local' → Employee.personUuid → AccountUuid）；Plan 06 seed 必须用同 key 格式
- **DM 查/建 复用 ai-bot getDirect** — findAll DirectMessage by members → 过滤 members 集合恰为 {bot, target} → 找到复用 / 否则 createDoc 新 DM
- **listener v1 用 2s poll 而非 live subscription** — RESEARCH §Open Questions #2 已定；v2 升级 live 订阅
- **死循环防护用 systemAccountUuid 作为 bot 标识** — Plan 04 service token 已用此 UUID；Plan 06 seed 后可换真 bot 账号
- **channel_type 映射用 attachedToClass 包含判断** — DirectMessage→'D'，PrivateChannel→'P'，其他→'O'；与 MM 约定对齐让 dispatcher 0 改动
- **register_command_listener 在 HulyIMProvider 是 no-op** — listener 走独立 HulyListener（webhook 模式）；Protocol 契约满足即可
- **@hcengineering/document 用本地 .d.ts shim + lookup helper** — npm 公网无 v0.7.423（Plan 04 deviation #1）；类型靠 shim，运行时 lookup 兜底
- **BRIDGE_TOKEN 配置为空时主动 401** — 防止运营误配让 webhook 变开放接口（NFR-05）
- **测试用 httpx.MockTransport（不是 respx）** — 项目无 respx；MockTransport 是 httpx 内置，captures URL/body/headers 同样能验证契约
- **main.py 用 IMListener Proto 抽象类型注解** — 解决 mypy "MattermostListener | None 不能接 HulyListener"；isinstance(_, IMListener) runtime_checkable 校验生效

---

## Plan 04 Decisions (2026-05-17)

- **tsx 而非 tsc** — sidecar 单文件场景；Dockerfile 不含 build 步骤，dev/prod 一致
- **fail-fast config** — loadConfig 缺一必需 env 立即抛错（不许半启动后 500）
- **non-blocking Huly connect** — sidecar 启动不等 Huly 就绪；healthz 反映状态（NFR-06）
- **/healthz + / 白名单不需 X-Bridge-Token** — docker healthcheck 必须能跑
- **CJS interop = default import + lazy lookup** — @hcengineering/* 是 esbuild CJS 输出；ESM 不能命名导入；lazy 同时兼容 vitest mock 与真运行时
- **@hcengineering/document 暂从依赖移除** — npm 公网只有 0.7.0；Plan 05 改用 chunter.Card 或 docker tarball 兜底
- **类型 shim 文件** — 上游 v0.7.423 npm publish 漏带 .d.ts；写 src/hcengineering-shims.d.ts 临时声明用到的接口子集
- **Immutable config** — Object.freeze + readonly；符合 CLAUDE.md immutability 约定
- **集成测使用 supertest** — createApp(config, healthState) 拆分让测试不需起真 server / 连真 Huly

---

## Plan 03 Decisions (2026-05-17)

- **业务服务由 plan 列的 9 个修正为 11 个** — 读上游 huly-selfhost compose.yml 发现漏 fulltext + kvs（核心依赖），补上
- **Elasticsearch 选 7.14.2 而非 8.12** — 与上游 huly-selfhost 一致；ingest-attachment 插件自动安装
- **Huly Redis 不重复起** — 复用项目独立 offboarding-redis:6380（v1 暂不启用 hulypulse）
- **HULY_SERVER_SECRET 不带 :? 强校验** — docker compose 全局解析 env，profile 隔离不阻断；改 runbook 显式提醒「启动 huly-stack 前必填」
- **MinIO 端口隔离 9091/9092** — 避项目原 MinIO 9000/9001 冲突
- **huly-bridge sidecar 仅占位 build path** — Plan 04 才实现 Dockerfile + src/；端口 7777 + BRIDGE_TOKEN + container_name `offboarding-huly-bridge` 作为契约固化

---

## Plan 01 Decisions (2026-05-17)

- **BotInvocationContext 不在本 plan 加 im_helpers 字段** — 保留 mm_helpers: dict 与 Phase 7 兼容；Plan 02 ABS-06 重构时再统一迁移（避免冲击 11 个 handler 实现）
- **DispatchFn 在 im.protocol 和 providers.base 都定义一份**（同结构 alias）— 让 providers/ 模块**不依赖** im/ 模块，保持单向依赖
- **BotHandlerRegistry 用显式 register** 而非全局 decorator — BotService 实例化时才有 self / session / flow_service 上下文，decorator 工程复杂度 > 收益
- **delete 操作 404 视为幂等成功** — Outline / Lark delete_document / delete_collection 收到 not_found 时不抛，便于重试安全
- **wecom / dingtalk stub 必须补齐新方法** — Protocol runtime_checkable 严格检查，不补齐 mypy 报错 + 切换 provider 时崩

---

*Last updated: 2026-05-17 after Phase 8 Plan 05 completion (Huly 业务接入层 + 反向通道 — sidecar IM/Doc 路由真实现 + Python provider/listener/route 全栈接通 + 73 测试 PASS + IM_PROVIDER=huly 一行切换可用)*
