# CLAUDE.md — 项目级 AI 协作约定

> 本文件由 Claude Code 在每次 session 开始时自动加载。所有 AI（含 subagent）开发本项目时**必须遵守**以下约定。
>
> 项目：offboarding-flow — AI 驱动的离职流程执行系统（LangGraph + FastAPI + Next.js）
> 全局规则继承自 `~/.claude/rules/common/`（coding-style / git-workflow / testing / performance / security 等），本文件仅记录**项目特定**约定。

---

## 1. 并行开发原则（首要）

**用户明确要求：能并行就并行开发**。

### 1.1 何时必须并行

- **独立的研究 / 调研任务** → 用 `Agent` 工具并发 spawn 多个 subagent，**单条消息多 tool call**
  - 反面教材：4 个研究维度逐个 spawn → 总耗时 = 4 个 max；正面：并发 spawn → 总耗时 = 1 个 max
- **同 phase 内独立的 plan** → 用 `subagent-driven-development` 模式拆任务并行执行
- **多文件 read** → 一条消息发多个 `Read` tool call
- **多个 grep / find** → 同样并行
- **CI 多 job** → workflow 拆并行 job
- **frontend + backend 联调** → 一边写后端 endpoint，一边写前端调用（用 mock 解耦）

### 1.2 何时必须串行

- 后续任务依赖前序任务的产出（如 LangGraph schema 必须先于节点实现）
- 数据库 migration 必须有序
- 涉及共享文件的写操作（避免冲突）

### 1.3 并行触发点速查

| 场景 | 工具 | 注意 |
|---|---|---|
| 调研 N 个维度 | `Agent` × N（一条 message，多 tool call）| 用 `run_in_background=true` |
| 实现 N 个独立模块 | `Agent` × N，互不引用对方文件 | 各自 commit |
| 读 N 个文件 | `Read` × N 并行 | 一条消息内 |
| Phase 内多 plan | `subagent-driven-development` skill | 看 plan 间依赖 |
| 前后端联调 | frontend + backend 各起一个 worktree | `using-git-worktrees` |

### 1.4 反模式（必须避免）

- ❌ Sequential agent calls 当其实可以并发
- ❌ 用单一 mega-agent 做本可拆分的多维度调研
- ❌ "先做完 A 再考虑 B" 当 A、B 实际无依赖

---

## 2. 测试要求

### 2.1 全流程测试（mandatory）

**用户明确要求：整个流程要全流程测试**。

- **每个 phase 完成后必须跑全流程 E2E**（不是 phase 内单元测试，而是从 P1 到当前 phase 的全链路验证）
- 全流程测试脚本放 `backend/tests/e2e/test_full_flow.py`
- 默认场景：`zhang.san` 起流程 → 走完 manager_review → hr_initial → 5 并行 → hr_final → applicant_final_confirm → archive
- 演示模式默认场景：起流程 → 10 节点全部 advance 走完 + 节点 result_text 校验 + node_results 聚合校验 + 申请人邮件聚合校验
- 演示模式异常场景：
  - 任意节点 return（必须正确回退到上游）
  - 任意关键节点 reject（必须正确终止）
  - 超时模拟（必须触发 timeout_scan + 重发提醒）
  - 证据缺失模拟（AI 报告必须识别）
  - GLM API down（必须降级，邮件无摘要但能发出）
  - QQ SMTP down（outbox 失败 + 重试 3 次 + alert）
  - 进程崩溃（docker restart 后流程进度无丢失）

### 2.2 E2E 测试用 browser-harness

**用户明确要求：E2E 测试用 browser-harness**。

**实施方案**：
- 主要用 `webapp-testing` skill（Playwright 后端）做浏览器自动化 E2E
- 备选：本仓库可考虑后续封装一个 `browser-harness/` 目录把 webapp-testing 的常用模式固化下来
- E2E 测试覆盖：
  - 邮件深链点击 → 自动登录 → 看到正确角色视图 → 三态决策提交 → 浏览器看到流程推进
  - HR Dashboard 列出所有流程 + 筛选 + 重发通知按钮
  - 申请人最终确认页时间线 + GLM 摘要展示
  - Mattermost @bot 命令触发后浏览器端能看到 / 收到对应变化
- E2E 测试放 `frontend/tests/e2e/`（Playwright spec）+ `backend/tests/e2e/test_browser_flow.py`（如果用 Python 驱动）

### 2.3 单元 / 集成测试

- pytest-asyncio mode=auto + fixture `loop_scope=session`
- polyfactory 生成测试数据（不要 factory-boy）
- httpx.AsyncClient + asgi-lifespan 做 API 集成测试
- 覆盖率门槛：80%（继承自全局 testing.md）
- TDD-first（继承自全局 testing.md）

---

## 3. 项目特定的工作流约定

### 3.1 PRD / 规划文档是 source of truth

- **PRD.md** 是产品定义（v0.4 当前）
- **`.planning/PROJECT.md`** 是项目宪法（GSD framework）
- **`.planning/REQUIREMENTS.md`** 是 v1 REQ-IDs（45 个）
- **`.planning/ROADMAP.md`** 是 6 phase + 1 加分 phase 拆分
- **`.planning/research/SUMMARY.md`** 是技术决策合成
- **`.planning/phases/0X-name/0X-CONTEXT.md`** 是 phase 实现决策

**任何代码实现都必须能追溯到上述文档的某个 REQ-ID 或决策**。新需求先入 PRD/REQUIREMENTS 再写代码。

### 3.2 CHANGELOG.md 每次更新

- 每次完成实现 / 修改 / 提交 → 追加到 `[Unreleased]` 段
- 分类：Added / Changed / Fixed / Security / Infrastructure / Discovered/Planned
- 完成 milestone 时切版本号

### 3.3 双层状态分离（项目最深的设计约束）

- **LangGraph checkpoint 是引擎私有数据**（PostgresSaver 自管，pickle 序列化，schema `langgraph`）
- **业务表是 UI / 审计 / 报表的 source of truth**（schema `app`，flow_instances / node_states / action_logs / notifications / notification_outbox / users）
- **节点函数必须双写**：业务表事务 commit → 才 invoke LangGraph
- **前端绝不读 LangGraph checkpoint**，只读业务表

### 3.4 节点函数幂等性是硬约束

- LangGraph `interrupt()` 抛 `GraphInterrupt` 后**节点函数会重跑**
- 所有 INSERT 必须 upsert（`ON CONFLICT DO NOTHING/UPDATE`）
- `notification_outbox` 表加 `UNIQUE(flow_id, node_state_id, channel)` 约束
- 节点函数模板用 `is_first_entry` 判断是否首次进入

### 3.5 凭证安全

- **绝对不要把以下凭证写进任何 git tracked 文件**：
  - QQ SMTP 授权码（16 位字母）
  - GLM API Key
  - Mattermost Bot Token
  - JWT Secret
  - PostgreSQL 密码
- 所有凭证只通过 `.env` 注入（已 `.gitignore`）
- `.env.example` 只放占位 `changeme_in_real_env`
- pre-commit gitleaks 钩子必须装且不许 skip

### 3.6 演示模式 vs 生产模式

- `APP_MODE=demo` 时所有邮件路由到 `DEMO_INBOX=1624456575@qq.com`，主题加角色前缀 + 正文加横幅
- `APP_MODE=prod` 时邮件走真实 `notifications.recipient`
- **启动日志必须显式打印 `APP_MODE`**（防上线没切回 prod）
- 前端 footer 必须显示当前 mode

---

## 4. 部署约定

- **目标环境**：`192.168.2.44`（GigaByte laios），内网
- **数据库**：独立 `offboarding-postgres` 容器（端口 5433），不复用其他业务的 PG
- **Redis**：独立 `offboarding-redis` 容器（端口 6380）
- **前端**：Next.js `output: 'export'` 静态导出，nginx 直接 serve（不跑 Node 运行时）
- **Mattermost**：已部署 `:8065`，team `laios`
- **MinIO**：已部署 `:9001` console / `:9000` API
- **部署命令**：`docker compose --env-file .env up -d` 在 44 执行

## 5. AI 能力边界（PRD §15.3）

**AI 可做**：总结 / 推理建议 / 生成报告 / 检测异常 / 自然语言查询
**AI 绝不可做**：三态决策 / 改流程模板 / 删记录 / 调外部业务 API / 改历史日志 / 替申请人确认 / 发非模板邮件

**所有 AI 输出必须带 disclaimer**：`*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*`

## 6. 中文化约定

- 所有代码注释 / commit message / 文档：中文（继承自全局 coding-style.md）
- 变量名 / 函数名 / 代码标识符：英文
- 用户面向文本（邮件 / Mattermost 消息 / UI label）：中文

## 7. Git 协作

- 默认分支：`main`
- 远端：`git@github.com:LaiosOvO/liuxin-interview.git`
- Commit message 格式（继承全局）：`<type>: <description>` (feat/fix/refactor/docs/test/chore/perf/ci)
- 严禁在本机 git config 改用户 / 邮箱
- 严禁 push 到 main / 强制 push（用户没明确要求时）
- 使用 `node /Users/admin/.claude/get-shit-done/bin/gsd-tools.cjs commit ...` 做 GSD 工作流相关 commit
- 普通代码 commit 用 `git commit`

## 8. 阅读参考项目

- 参考项目 clone 到 `~/ai/ref/{category}/`（分类：agent / workflow / desktop / search / tutorial 等）
- 阅读后必须写 `docs/reading-{project}-{date}.md` 到当前项目
- 重点写"可借鉴什么 + 文件路径"，不要写项目介绍
- 详见全局 reference-projects.md

## 9. 文件组织（继承 coding-style.md）

- 单文件 < 800 行（推荐 200-400 行）
- 函数 < 50 行
- 嵌套 < 4 层
- 按 feature/domain 分模块（不按 type 分）
- 不可变数据（immutability）— 永远新建对象不修改原对象

---

*Last updated: 2026-05-16 — 项目 init 阶段，记录用户的核心协作约定*
