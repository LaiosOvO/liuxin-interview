# Changelog

> 项目：offboarding-flow — AI 驱动的离职流程执行系统
> 格式：基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 1.1.0
> 版本：基于 [SemVer](https://semver.org/lang/zh-CN/)

所有 notable 变更将记录在本文件，按时间倒序排列。
每次实现新功能 / 修复 bug / 重构 / 调整文档结构都会追加到 `[Unreleased]` 节，正式发布版本时再切到对应版本号。

---

## [Unreleased]

### Added

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
