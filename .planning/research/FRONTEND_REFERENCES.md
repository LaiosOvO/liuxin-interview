# Frontend 参考项目调研

> 调研日期：2026-05-16
> 目标技术栈：Next.js 15 (App Router, `output:'export'`) + React 19 + TypeScript 5.x + Tailwind v4 + shadcn/ui + pnpm
> 范围：HR 离职流程内部系统的前端（工单详情、HR 总览、状态机可视化、时间线、登录中转）

---

## 总结（TL;DR）

1. **骨架直接用 `Kiranism/next-shadcn-dashboard-starter` (6.4k★, MIT, Next.js 16 + React 19 + Tailwind v4 + shadcn/ui)**——它就是为目标技术栈量身定做的，里面的 `app-sidebar` / `header` / `page-container` / `nav-main` / `org-switcher` 可零修改套用。Next.js 16 与 Next.js 15 的 App Router API 几乎一致，只需把 `package.json` 里的 `next` 版本固定到 15.x 即可降级。
2. **核心 feature 代码从 `satnaing/shadcn-admin` (12k★, MIT, Vite + TanStack Router) 拷贝**——它是 Vite，不能整套 fork，但 `src/features/tasks/`（数据表 + 行内动作 + 抽屉编辑）几乎就是 HR 总览页的成品，`src/features/chats/index.tsx` 是**完美的"左侧列表 + 右侧详情"二栏布局**（直接对应 P0-1 的工单审批页），把这两个 feature 整个目录拷过来调路径即可。
3. **状态机可视化（P1-3）用 `@xyflow/react`（36k★, MIT）**，参考 `xyflow/xyflow/examples/react/src/examples/Layouting` 和 `SaveRestore` 两个 example 实现"节点高亮当前激活态"；不要 fork 整套 `Azim-Ahmed/Automation-workflow`（用 React 18 + react-scripts + antd 4，技术栈不匹配，只读源码取灵感）。
4. **时间线 + 登录中转页几乎没有现成的，直接用 shadcn `Card` + `Separator` + lucide 图标自己写 50 行搞定**，因为太轻量、太业务化，找现成不如自己写。

---

## 推荐 1：Kiranism/next-shadcn-dashboard-starter — 整套骨架

- **URL**: https://github.com/Kiranism/next-shadcn-dashboard-starter
- **Stars**: 6,423
- **Last commit**: 2026-05-15（活跃）
- **License**: MIT（商业友好）
- **技术栈匹配度**: ★★★★★（几乎完全匹配）
  - Next.js 16 (App Router) — 与目标 Next.js 15 兼容，把 `next` 版本号改回 15.x 即可
  - React 19 ✓
  - TypeScript ✓
  - Tailwind CSS v4 ✓
  - shadcn/ui ✓
  - 包管理：默认 Bun，但有 `package-lock.json`，pnpm 直接 `pnpm install` 也能用
  - **差距**：自带 Clerk（认证）、Sentry、Recharts、dnd-kit、Tabler Icons 等。不需要的依赖直接卸载（Clerk 必删，本项目用自家 JWT）。

- **可借鉴**:
  - `src/components/layout/app-sidebar.tsx` — **侧栏直接抄**（HR 总览页、员工视图共用）
  - `src/components/layout/header.tsx` + `page-container.tsx` — 顶栏 + 内容容器
  - `src/components/nav-main.tsx` / `nav-user.tsx` / `nav-projects.tsx` — 菜单结构
  - `src/features/products/` — TanStack Table + React Query + Zod，**直接套到 HR 流程总览表格**（带搜索、过滤、分页、列定义）。`src/features/products/components/` 里的 `data-table-bulk-actions` / `data-table-row-actions` 是核心
  - `src/features/users/` — 用户列表 + 行内编辑 dialog，可改成"流程关系人"管理
  - `src/features/kanban/` — dnd-kit 实现的看板，**演示模式下可视化各节点状态**（P2 加分）
  - `src/features/profile/` — 个人资料页布局可套用到员工自己流程的简化视图
  - `src/app/dashboard/` 的 parallel routes 模式 — 演示侧栏 + 详情同时加载的最佳实践
  - `src/components/kbar/` — 命令面板（Cmd+K 快捷搜索流程），HR 总览的加分项

- **不可借鉴**:
  - Clerk 集成（`@clerk/nextjs`）必须完全移除，本项目用 JWT
  - Sentry 监控可选保留
  - `auth` 目录的登录页基于 Clerk，重写
  - 自带的 `oxlint` 工具链可换回 ESLint（看团队偏好）

- **实际操作建议**:
  ```bash
  cd ~/ai/ref/frontend && \
    git clone https://github.com/Kiranism/next-shadcn-dashboard-starter
  # 重点阅读路径（按优先级）：
  # 1. src/app/dashboard/layout.tsx —— 整体布局
  # 2. src/components/layout/app-sidebar.tsx —— 侧栏导航
  # 3. src/features/products/components/ —— 数据表完整套件（迁移到 frontend/components/flow-table/）
  # 4. src/features/kanban/ —— 状态可视化备选方案
  # 5. src/components/nav-main.tsx —— 菜单数据结构
  ```

---

## 推荐 2：satnaing/shadcn-admin — 拷 Feature 代码

- **URL**: https://github.com/satnaing/shadcn-admin
- **Stars**: 12,050
- **Last commit**: 2026-05-16（极活跃）
- **License**: MIT
- **技术栈匹配度**: ★★★（部分）
  - React 19 ✓
  - TypeScript ✓
  - Tailwind v4 ✓
  - shadcn/ui ✓
  - **不匹配**：Vite + TanStack Router（不是 Next.js App Router）—— 所以**整套不能 fork**，只能拷贝 `src/features/` 里的 React 组件代码
  - 路由部分（`createFileRoute(...)`）需要全部转成 Next.js 的 `app/*/page.tsx`
  - 包管理：pnpm ✓

- **可借鉴**（直接拷贝代码，调 import 路径就能用）:
  - **`src/features/tasks/`** — **P0-1 工单审批的 HR 总览视图基础**
    - `tasks-table.tsx` + `tasks-columns.tsx` — 完整 TanStack Table（带 faceted filter、列可见性切换）
    - `data-table-row-actions.tsx` — 每行的"继续/退回/拒绝"下拉菜单
    - `tasks-mutate-drawer.tsx` — 右侧滑出抽屉编辑（适合"自由文本输入"动作面板）
    - `data-table-bulk-actions.tsx` — HR 批量操作（v2 可选）
  - **`src/features/chats/index.tsx`** — **P0-1 工单详情页的"左列表 + 右详情" 二栏布局**
    - 左侧是会话列表（→ 改成"待办流程列表"）
    - 右侧是消息流（→ 改成"流程节点详情 + 操作日志时间线 + 三态按钮 + 文本框"）
    - 已经处理了**移动端 vs 桌面**的响应式切换（`mobileSelectedUser` 状态），无需自己写
  - **`src/features/users/`** — 与 tasks 完全同构的另一个 data-table 实例，可作为"模板"快速派生第二个表
  - `src/components/layout/` — `nav-group.tsx` 支持分组菜单（HR / 员工 / 设置），比 Kiranism 的更适合多角色场景
  - `src/components/confirm-dialog.tsx` + `sign-out-dialog.tsx` — 确认对话框
  - `src/components/long-text.tsx` — 长文本省略 + tooltip（流程备注列必备）
  - `src/components/data-table/` — 抽出的可复用 data table 基础

- **不可借鉴**:
  - 整套路由系统（TanStack Router → 必须改写为 App Router）
  - `src/main.tsx` / `src/routeTree.gen.ts` — 跳过
  - 自带 Clerk 认证 — 改 JWT
  - `vite.config.ts` — 用不上

- **实际操作建议**:
  ```bash
  cd ~/ai/ref/frontend && \
    git clone https://github.com/satnaing/shadcn-admin
  # 拷贝策略（在 frontend/ 目录内执行）：
  # 1. cp -r ~/ai/ref/frontend/shadcn-admin/src/features/tasks frontend/features/flows/
  # 2. cp -r ~/ai/ref/frontend/shadcn-admin/src/features/chats frontend/features/inbox/
  # 3. cp ~/ai/ref/frontend/shadcn-admin/src/components/data-table/* frontend/components/data-table/
  # 4. cp ~/ai/ref/frontend/shadcn-admin/src/components/{long-text,confirm-dialog}.tsx frontend/components/
  # 然后批量替换：
  #   - 把 createFileRoute → 删掉，迁到 app/(dashboard)/flows/page.tsx
  #   - 把 @tanstack/react-router 的 useNavigate → next/navigation 的 useRouter
  ```

---

## 推荐 3：@xyflow/react（前 React Flow）— 状态机可视化

- **URL**: https://github.com/xyflow/xyflow
- **Stars**: 36,604
- **Last commit**: 2026-05-16（极活跃）
- **License**: MIT
- **技术栈匹配度**: ★★★★★（库无关，纯 React 组件）
- **不是 fork，是 npm 依赖**：`pnpm add @xyflow/react`

- **可借鉴**（参考 example 目录读源码，不复制代码）:
  - `xyflow/xyflow/examples/react/src/examples/Layouting/` — **自动布局**（用 dagre），离职流程 DAG 节点自动排版
  - `xyflow/xyflow/examples/react/src/examples/SaveRestore/` — 节点状态持久化
  - `xyflow/xyflow/examples/react/src/examples/CustomNode/` — **自定义节点样式**（用于"已完成绿色 / 进行中蓝色 / 已退回橙色"高亮）
  - `xyflow/xyflow/examples/react/src/examples/NodeToolbar/` — 节点悬浮显示详情
  - `xyflow/xyflow/examples/react/src/examples/Overview/` — 完整的"节点 + 边 + minimap + controls"组合

- **实际操作建议**:
  ```bash
  # 不 clone，直接读官方文档 + 安装包：
  # pnpm add @xyflow/react reactflow dagre
  # 读：https://reactflow.dev/examples/layout/dagre
  # 在 frontend/components/flow-graph/ 实现：
  #   - StateMachineGraph.tsx：渲染节点 + 边
  #   - 节点根据 status (done/active/pending/returned) 切换 className
  ```

- **配合使用**：把 `Azim-Ahmed/Automation-workflow` (307★) **当成抄思路的反面教材**（technicalitye 是 react-scripts + antd 4 + reactflow 11，不匹配新栈，但里面的 `Nodes/` 目录展示了"如何设计可配置节点"，10 分钟扫一眼即可）。

---

## 单独的组件 / 模板（不是整套项目）

### shadcn/ui 官方 blocks（https://ui.shadcn.com/blocks）

**直接 `npx shadcn add` 即可拉到本地**：

| Block | 用途 |
| ----- | ---- |
| `dashboard-01` | HR 总览页骨架（侧栏 + chart + data table） |
| `sidebar-07` | 可折叠到图标的侧栏（推荐） |
| `sidebar-03` | 带二级菜单的侧栏（HR / 员工 / 设置 分组） |
| `login-03` / `login-04` | 登录页（普通账密登录） |
| `login-01` | 极简登录（适合一键登录中转页改造） |

### Tailwind UI 替代

不推荐——Tailwind UI 自家收费且组件多基于 React 18 + Tailwind 3。直接用 shadcn/ui blocks 已经覆盖。

### React Flow 官方 demo
直接看 https://reactflow.dev/examples，无需 clone。

### Timeline 组件
- `Tourniercy/shadcn-timeline` (45★, 无 license) — **不推荐**：star 少且无明确 license。直接用 shadcn 的 `Card` + `Separator` + `Avatar` + 一个 `border-l` 的左竖线，30 行 JSX 搞定。**这是 P1-4 的最快路径**。

---

## 不推荐 / 已淘汰

| 项目 | 理由 |
| ---- | ---- |
| `TailAdmin/free-nextjs-admin-dashboard` (2.4k★) | 用纯 Tailwind 自写组件，不基于 shadcn/ui，组件 API 不兼容；视觉风格偏 SaaS marketing |
| `themeselection/materio-mui-nextjs-admin-template-free` (1.9k★) | 基于 Material UI，与目标栈完全不兼容 |
| `NextAdminHQ/nextjs-admin-dashboard` (495★) | 同上，非 shadcn 体系 |
| `vbenjs/vue-vben-admin` (32k★) | Vue3，仅作为"中文 admin 设计美学"参考可截图 |
| `soybeanjs/soybean-admin` (14k★) | Vue3 + Naive UI，同上仅美学参考 |
| `ant-design/ant-design-pro` (38k★) | React，但深度绑定 antd，与 Tailwind v4 + shadcn 风格冲突 |
| `Azim-Ahmed/Automation-workflow` (307★) | React 18 + react-scripts + antd 4 + reactflow 11，技术栈太老，无 license。**仅作灵感来源** |
| `Tourniercy/shadcn-timeline` (45★) | star 少 + 无 license，自己写更快 |
| `TheOrcDev/orcish-tanstack-dashboard` 等 < 200★ | 维护性差或质量未验证 |

**Camunda Tasklist UI / Activepieces / DolphinScheduler 的前端**调研结论：
- Camunda Tasklist 是 Angular + Camunda 私有组件库，无可借鉴
- Activepieces 是 Angular + nx monorepo
- DolphinScheduler UI 是 Vue3 + ant-design-vue
- **结论**：审批/工作流系统的开源前端没有 Next.js + shadcn 栈的合适参考，必须从通用 admin 模板（Kiranism + satnaing）+ React Flow 自己组合

---

## 给 frontend phase planner 的建议

### Phase 4（前端启动）的第一周操作清单

1. **Day 1**：
   - `cd ~/ai/ref/frontend && git clone https://github.com/Kiranism/next-shadcn-dashboard-starter`
   - `cd ~/ai/ref/frontend && git clone https://github.com/satnaing/shadcn-admin`
   - 在当前项目按推荐 1 的 README 操作创建 `frontend/` 子目录，并把 `package.json` 里的 `next: ^16` 改为 `next: ^15.0.0`，删除 `@clerk/*` 和 `@sentry/*` 依赖
   - 跑通 `pnpm dev`，确认侧栏 + 空 dashboard 可访问

2. **Day 2**：从 `satnaing/shadcn-admin` 拷贝 `src/features/tasks/` → `frontend/src/features/flows/`，迁移所有 import 路径（`@tanstack/react-router` → `next/navigation`，删除 `createFileRoute`），适配为 `app/(dashboard)/hr/flows/page.tsx`。**用 mock 数据先跑通页面**。

3. **Day 3**：从 `satnaing/shadcn-admin` 拷贝 `src/features/chats/index.tsx` → `frontend/src/features/inbox/index.tsx`，把"消息流"换成"流程节点操作日志"，"会话列表"换成"我的待办流程"。三态按钮（继续/退回/拒绝）+ 自由文本输入框直接复用其 `Send` 按钮区域设计。

4. **Day 4**：写 `frontend/src/components/state-machine-graph/` 用 `@xyflow/react`，参考 reactflow.dev 的 Layouting + CustomNode 两个 example 实现节点高亮。

5. **Day 5**：写两个完全自定义的小页面（这部分**绝对没有现成参考**，因为太业务化）：
   - `app/auth/bridge/page.tsx` — 一键登录过渡页：解 token → POST `/api/auth/exchange` 拿 session → 跳到目标 `flow_id` 详情。UI 就是一个 Loader + "正在以 XX 身份登录..." 文案
   - `app/confirm/[flow_id]/page.tsx` — 申请人最终确认页（PRD §4.5），用 shadcn `Card` + `Separator` 渲染汇总表格 + 两个按钮（确认 / 退回）

### 必须自己写的组件（无现成参考）

| 组件 | 原因 |
| ---- | ---- |
| 一键登录中转页 (`/auth/bridge?token=xxx`) | 业务专属，安全敏感，自己写 50 行 |
| 申请人最终确认聚合页 (`/confirm/[flow]`) | PRD §4.5 自定义版式，直接抄 PRD 中的 ASCII 草图布局 |
| 演示模式横幅 (APP_MODE=demo) | 在 Layout 加 4 行：检测 env，渲染黄色条 |
| Mattermost 推送预览组件（v2 可选） | 没有现成 |

### 抄代码优先级（从快到慢）

1. **Kiranism 的 layout 套件**（侧栏 + 顶栏 + 容器）— 半天搞定整站骨架
2. **satnaing 的 tasks feature**（数据表 + 行内动作）— 1 天搞定 HR 总览
3. **satnaing 的 chats index.tsx**（二栏布局）— 1 天搞定工单详情
4. **xyflow + 自写 CustomNode**（状态机可视化）— 1 天
5. **自写时间线 / 登录中转 / 最终确认页** — 各半天

### 关键风险提醒

- **Kiranism 是 Next.js 16，本项目要求 Next.js 15**：实际两者的 App Router API 95% 相同，但 `output: 'export'` 静态导出模式下，要禁用所有 server actions / dynamic routes 的 SSR。`src/features/products` 里的 React Query + API mock 模式正好支持纯 CSR，符合静态导出。
- **satnaing 用 TanStack Router**：拷贝 feature 时**只拷 `components/` 和 `data/`，不拷 `index.tsx` 的 route 定义部分**。
- **Clerk 必删干净**：搜索 `@clerk` 全量替换。本项目用 JWT + 一键登录 token 机制，认证流完全不同。
- **Tailwind v4 升级注意**：satnaing 已迁 v4，Kiranism 也是 v4，拷贝时 className 完全兼容。若团队习惯 v3，要回退 PostCSS 配置。
