# 前端 E2E 测试（Phase 5 才填）

## 范围

这里放浏览器 E2E（Playwright spec）。Phase 1（本提交）只占位，实际 spec Phase 5 才落地。

## 实施方案（CLAUDE.md §2.2）

- 主要用 `webapp-testing` skill（Playwright 后端）做浏览器自动化
- spec 文件命名：`xxx.spec.ts`（Playwright 默认约定）
- 覆盖场景：
  - 邮件深链点击 → 自动登录 → 看到正确角色视图 → 三态决策提交 → 浏览器看到流程推进
  - HR Dashboard 列出所有流程 + 筛选 + 重发通知按钮
  - 申请人最终确认页时间线 + GLM 摘要展示
  - Mattermost @bot 命令触发后浏览器端能看到 / 收到对应变化

## 怎么跑（Phase 5 落地后）

```bash
cd frontend
pnpm install
pnpm exec playwright install chromium
pnpm test:e2e   # 跑所有 .spec.ts
```

## Phase 1 / Phase 2 / Phase 3 / Phase 4

这些 phase 没有 UI，只跑 `backend/tests/e2e/`（curl-based 后端 E2E）。
