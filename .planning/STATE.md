# Project State: offboarding-flow

## Project Reference

See: [.planning/PROJECT.md](./PROJECT.md) (updated 2026-05-16)

**Core value:** 让"流程状态机"端到端可见且可驱动 — 一封邮件 → 一键登录 → 一段文本 + 一次决策 → 流程自动推进直到申请人最终确认
**Current focus:** Phase 2（双写规范完整化 + 8 节点扩展 + 申请人最终确认）

---

## Current Status

**Stage:** Phase 1 完成 — 35 测试全通过 + 4 业务端点 + LangGraph 骨架就位

**Last completed:** Phase 1 全部 7 个 plan（3 个 wave 并行执行）— commit `bf20b03`（实现） + `29b657d`（docs）

**Next action:** 二选一：
- A) 在 192.168.2.44 跑 `bash scripts/dev_up.sh && bash scripts/smoke_test.sh` 做部署冒烟（验证 docker compose 真起来）
- B) `/gsd:discuss-phase 2` 或 `/gsd:plan-phase 2` 进入 Phase 2

---

## Roadmap Summary

| # | Phase | Status |
|---|-------|--------|
| 1 | 基建 + LangGraph 骨架 | ✓ Complete |
| 2 | 双写规范 + 节点完整化 + 申请人确认 | ○ Pending |
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

---

*Last updated: 2026-05-16 after Phase 1 complete (commit bf20b03)*
