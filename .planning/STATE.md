# Project State: offboarding-flow

## Project Reference

See: [.planning/PROJECT.md](./PROJECT.md) (updated 2026-05-16)

**Core value:** 让"流程状态机"端到端可见且可驱动 — 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进直到申请人最终确认
**Current focus:** Phase 2 完成 → 下一步 Phase 3（鉴权 + 深链 JWT 一键登录）

---

## Current Status

**Stage:** Phase 2 完成 — 126 测试通过 + 10 节点完整拓扑 + 双写规范完整 + 申请人最终确认（DF-02 ★★★★★）

**Last completed:** Phase 2 全部 6 个 plan（4 个 wave）— commits 9c113cb / d4349cb / 6145706 / a951e34 + Plan 06

**Next action:** 二选一：
- A) 跑全流程 E2E：`OFFBOARDING_E2E_BASE_URL=http://192.168.2.44:8000 uv run pytest backend/tests/e2e/ -v -m e2e`
- B) `/gsd:plan-phase 3` 进入 Phase 3（鉴权 + 深链 JWT）

---

## Roadmap Summary

| # | Phase | Status |
|---|-------|--------|
| 1 | 基建 + LangGraph 骨架 | ✓ Complete |
| 2 | 双写规范 + 节点完整化 + 申请人确认 | ✓ Complete |
| 3 | 鉴权 + 深链 JWT 一键登录 | ○ Pending |
| 4 | 通知 + Bot 入口 + AI 增强 + Seed + 逾期模拟 | ○ Pending |
| 4.5 | 加分项：自动动作节点演示 | ○ Pending |
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
| 2026-05-16 | plan-phase 2 --auto | 6 个 plan 落盘（4 个 wave）+ 全部执行（126 测试通过 + 双写规范完整 + 10 节点 + 申请人确认 + recover CLI）+ commits 9c113cb / d4349cb / 6145706 / a951e34 |

---

*Last updated: 2026-05-16 after Phase 2 complete*
