# Project State: offboarding-flow

## Project Reference

See: [.planning/PROJECT.md](./PROJECT.md) (updated 2026-05-16)

**Core value:** 让"流程状态机"端到端可见且可驱动 — 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进直到申请人最终确认
**Current focus:** Phase 4（通知 outbox + Bot 入口 + AI 增强 + Seed + 逾期模拟）— Phase 2 + Phase 3 已并行完成并 merge

---

## Current Status

**Stage:** Wave A 完成（Phase 2 + Phase 3 并行 worktree → merge main）— 199 测试在位（126 + 73）

**Last completed:**
- Phase 2: `worktree-phase-2-offboarding` → merged main（6 commits 9c113cb..326ffd8）— FLOW-02/04/05/06 + 10 节点完整 + 申请人最终确认（DF-02 ★★★★★）
- Phase 3: `worktree-phase-3-auth` → merged main（6 commits 609c139..16ce4db）— AUTH-01..04 + JWT + Redis NX EX jti + 深链 query string + 节点变更失效 hook

**Next action:** Wave B 并行：
- `/gsd:plan-phase 4 --auto` — 通知 outbox + Bot 入口 + AI 增强 + Seed + 逾期模拟
- `/gsd:plan-phase 4.5 --auto` — 加分项 AutoNode 演示

---

## Roadmap Summary

| # | Phase | Status |
|---|-------|--------|
| 1 | 基建 + LangGraph 骨架 | ✓ Complete |
| 2 | 双写规范 + 节点完整化 + 申请人确认 | ✓ Complete |
| 3 | 鉴权 + 深链 JWT 一键登录 | ✓ Complete |
| 4 | 通知 + Bot 入口 + AI 增强 + Seed + 逾期模拟 | ○ Pending（Wave B 即将启动）|
| 4.5 | 加分项：自动动作节点演示 | ○ Pending（Wave B 并行）|
| 5 | 前端 Next.js + 多角色 + 申请人时间线 + 逾期标签 | ○ Pending |
| 6 | 部署 + 演示模式切换 + 超时扫描 + 运维脚本 + 演示打磨 | ○ Pending |

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

---

*Last updated: 2026-05-16 after Wave A merge (Phase 2 + Phase 3 → main)*
