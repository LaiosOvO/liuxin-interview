# Project State: offboarding-flow

## Project Reference

See: [.planning/PROJECT.md](./PROJECT.md) (updated 2026-05-16)

**Core value:** 让"流程状态机"端到端可见且可驱动 — 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进直到申请人最终确认
**Current focus:** Phase 8 IM/Doc 全抽象 + Huly 接入 — Plan 01 (IM 抽象层 + DocProvider/IMProvider 完善 + HandlerRegistry) **已完成**

---

## Current Status

**Stage:** Phase 8 Plan 01 完成 — IM/Doc 抽象基座就位（436 测试收集，58 个新覆盖，新代码 100% 行覆盖）

**Last completed:**
- Phase 8 Plan 01: IMListener Protocol + dispatch_message + DocProvider 3 新 lifecycle 方法 + IMProvider register hook + BotHandlerRegistry（5 commits b27eb2d..c358edc）— ABS-01..05 5 个 REQ 全部 Complete
- Phase 7+ (2026-05-17): 协作文档抽象 + 按员工分文件夹 + 生产级 DAG + 完整 E2E（commit 51b1062）
- Phase 2-6 + 4.5: 全部历史 phase 已 merge main

**Next action:** Phase 8 后续 plan：
- Plan 02 (ABS-06 节点元数据外提到 config/nodes.yaml)
- Plan 03 (HulyDocProvider 实现 — 复用 ABS-03 接口)
- Plan 04 (HulyListener / HulyIMProvider 实现 — 复用 IMListener Protocol)
- Plan 05/06/07 (Huly bot + seed + MCP server)

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
| 8 | IM/Doc 全抽象 + Huly 接入 + 流程 MCP 化 | ◐ In Progress（Plan 01 ✓；Plan 02..07 待执行）|

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

---

## Plan 01 Decisions (2026-05-17)

- **BotInvocationContext 不在本 plan 加 im_helpers 字段** — 保留 mm_helpers: dict 与 Phase 7 兼容；Plan 02 ABS-06 重构时再统一迁移（避免冲击 11 个 handler 实现）
- **DispatchFn 在 im.protocol 和 providers.base 都定义一份**（同结构 alias）— 让 providers/ 模块**不依赖** im/ 模块，保持单向依赖
- **BotHandlerRegistry 用显式 register** 而非全局 decorator — BotService 实例化时才有 self / session / flow_service 上下文，decorator 工程复杂度 > 收益
- **delete 操作 404 视为幂等成功** — Outline / Lark delete_document / delete_collection 收到 not_found 时不抛，便于重试安全
- **wecom / dingtalk stub 必须补齐新方法** — Protocol runtime_checkable 严格检查，不补齐 mypy 报错 + 切换 provider 时崩

---

*Last updated: 2026-05-17 after Phase 8 Plan 01 completion (IM/Doc 抽象 + HandlerRegistry)*
