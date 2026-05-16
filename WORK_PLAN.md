# AI 离职流程系统 — 工作安排

> 起草日期：2026-05-16
> 配套：`PRD.md` v0.3 / `deploy/mattermost/ACCOUNTS.md`
> 目标产出：面试可演示的端到端 demo + 完整设计文档

---

## 0. 当前进度速览

| 项                           | 状态 | 备注                                           |
| ---------------------------- | ---- | ---------------------------------------------- |
| PRD v0.3                     | ✅   | 通用节点结构、申请人最终确认节点已收敛         |
| Mattermost 部署              | ✅   | `http://192.168.2.44:8065`（WSL2 Docker）       |
| 9 个测试账号 + 6 个 team     | ✅   | 邮箱 `+alias` 分发到 3 个真收件箱              |
| AI Bot + PAT                 | ✅   | `offboarding-bot` token 已落到 `hr/.env`        |
| SMTP 授权码                  | ⏳   | 你需要去 QQ 邮箱后台生成 16 位授权码           |
| JWT_SECRET                   | ⏳   | `openssl rand -hex 32`，一行命令               |
| LangGraph 状态机             | ⏳   | 未开工                                         |
| FastAPI 后端                 | ⏳   | 未开工                                         |
| Next.js 前端                 | ⏳   | 未开工                                         |
| design.md（架构文档）        | ⏳   | 等 PRD 稳定后再写                              |

---

## 1. 阶段切分（M1 → M5）

### M1：通信链路打通（demo 最小心跳）

> **目标**：能给三个真邮箱发出测试邮件、能让 Bot 在 Mattermost 发卡片消息。证明三方互通后，后续工作无环境阻塞。

| 任务 | 输入 | 输出 | 验收 |
|---|---|---|---|
| 1.1 配置 QQ SMTP 授权码 | QQ 邮箱后台 → 设置 → 账户 → POP3/SMTP 服务 | `hr/.env` 中 `SMTP_PASSWORD` 填入 | 命令行 `aiosmtplib` 一行测试发件成功 |
| 1.2 生成 JWT_SECRET | `openssl rand -hex 32` | `hr/.env` 中 `JWT_SECRET` 填入 | — |
| 1.3 编写 `tools/smtp_ping.py` | `hr/.env` | 给 3 个真邮箱各发 1 封测试邮件 | 3 个邮箱都能收到 |
| 1.4 编写 `tools/mm_ping.py` | bot token | Bot 在 `laios` team 的某 channel 发一条消息 | 你在 Mattermost UI 能看到 bot 发的消息 |
| 1.5 编写 `tools/mm_dm.py` | bot token + 目标 username | Bot 给指定用户发 DM 卡片消息（带 advance/return/reject 按钮） | zhang.san 收到 DM，按钮可点击（先不要求按钮真生效） |

**M1 完成标准**：你能用一条命令触发 bot 给 zhang.san 发卡片消息，三个真邮箱收得到 SMTP 邮件。

### M2：状态机骨架（LangGraph + Postgres Checkpointer）

| 任务 | 输出 | 验收 |
|---|---|---|
| 2.1 起 Postgres + Redis 容器 | `docker-compose.yml` 在 `hr/backend/` | postgres / redis 可在 192.168.2.44 上跑 |
| 2.2 LangGraph StateGraph 骨架 | `flow_engine/graph.py` 含 9 个节点（apply、manager_review、hr_initial、设备/权限/交接/财务、legal_sign、hr_final、applicant_final_confirm、archive） | `compile()` 不报错；导出 ASCII / Mermaid 图 |
| 2.3 通用节点函数模板 | `flow_engine/nodes/generic_human_node.py`（PRD §4.2 通用节点结构） | 单测：进入节点 → interrupt → 外部 update_state → 恢复 → 路由 |
| 2.4 Postgres checkpointer | `langgraph.checkpoint.postgres.PostgresSaver` 接入 | 进程重启后从最近 checkpoint 恢复 |
| 2.5 数据表迁移 | `migrations/001_init.sql` 创建 PRD §6 四张表 | 迁移可幂等执行 |

**M2 完成标准**：跑 `pytest flow_engine/tests/test_graph_e2e.py`，从 apply 节点一路通过 9 个 interrupt 推进到 archive。

### M3：API + 深链鉴权（PRD §6.2）

| 任务 | 输出 | 验收 |
|---|---|---|
| 3.1 FastAPI 项目骨架 | `hr/backend/app/` | `/health` 返回 200 |
| 3.2 一次性 JWT 签发 | `app/auth/deeplink.py` | 单测 sign + verify + jti 消费 |
| 3.3 `POST /api/auth/deeplink/exchange` | token → session cookie | 集成测：携 token 调一次 → 200，再调失败 |
| 3.4 `GET /api/flows/{id}/nodes/{nid}/view` | 按 role 渲染节点详情 | role=it / role=hr 返回不同 payload |
| 3.5 `POST /api/flows/{id}/nodes/{nid}/actions` | advance / return / reject | 写 action_logs、调 LangGraph update_state |
| 3.6 Notification gateway | 节点进入 interrupt 时并行触发 SMTP + Mattermost | 收件箱真能收到带深链按钮的邮件 |

**M3 完成标准**：纯后端跑 demo——curl 起一个流程，邮件到达 li.si 收件箱，点击邮件按钮跳到 `/api/auth/deeplink/exchange` 拿到 session，再 curl 推进节点，流程进入下一节点。

### M4：前端（Next.js + React Flow）

| 任务 | 输出 | 验收 |
|---|---|---|
| 4.1 Next.js 项目骨架 | `hr/web/` | `npm run dev` 起在 :3000 |
| 4.2 通用节点详情页 | `app/flow/[id]/node/[nid]/page.tsx` | 渲染 PRD §4.2 那张表单 |
| 4.3 状态机时间线视图 | React Flow 渲染 DAG，已完成 / 当前 / 未来三色 | 与 LangGraph 节点状态实时一致 |
| 4.4 HR 总览 dashboard | 列出所有 in-flight 流程、卡点告警 | 支持过滤 / 排序 |
| 4.5 申请人最终确认页 | 聚合时间线 + 三态决策 | PRD §4.5 |

**M4 完成标准**：演示者点邮件深链 → 浏览器自动登录 → 看到角色专属页面 → 提交决策 → 下个角色收到邮件，肉眼可见的端到端闭环。

### M5：演示打磨

| 任务 | 输出 |
|---|---|
| 5.1 录端到端演示视频 | `docs/demo.mp4`（5 分钟内） |
| 5.2 演示讲稿 | `docs/demo-script.md`（讲什么、点什么、强调什么） |
| 5.3 把 `design.md` 写完 | 系统架构、关键决策、开源对比、踩坑总结 |
| 5.4 README 重写 | 一句话定位 + Quick Start + 截图 |

---

## 2. 立即要做（M1 起步动作）

| 序号 | 你做 | 我做 |
|---|---|---|
| ① | QQ 邮箱后台开 SMTP，拿到 16 位授权码，告诉我 | 写到 `hr/.env` |
| ② | — | 写 `tools/smtp_ping.py` 并跑 |
| ③ | 收 3 封测试邮件验证 | — |
| ④ | — | 写 `tools/mm_dm.py` 给 zhang.san 发卡片消息 |
| ⑤ | 用 `zhang.san / laios1855` 登录 Mattermost 看消息 | — |

---

## 3. 设计待决问题（不阻塞 M1，但 M2 前要定）

| 问题 | 选项 | 倾向 |
|---|---|---|
| Q1: LLM 在系统里具体在哪里起作用？ | (a) 离职原因结构化抽取 / (b) 各节点 result_text 自动摘要 / (c) 卡点诊断 / (d) 都不用，只是状态机 | 优先做 (b) — 把每个节点的自由文本压缩成结构化摘要，在 §4.5 申请人最终确认时让 AI 给离职员工写一段"流程小结" |
| Q2: 流程模板是否硬编码？ | (a) Python 类硬编码（v1）/ (b) JSON/YAML 配置 / (c) 数据库表 | 硬编码 Python 类（v1），符合 PRD §1.3 |
| Q3: 节点失败重试策略？ | (a) 不重试，人工介入 / (b) 指数退避 3 次 | 人工介入（一致用三态决策的 return） |
| Q4: 并行节点 fan-in 等待策略？ | (a) 全部完成才推进 / (b) 大多数完成 | 全部完成（业务必须） |

---

## 4. 风险 / 阻塞项

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| QQ 邮箱被限流 | 短时间发送大量测试邮件 | 加单流程发送间隔 ≥ 30s；演示用 mailpit 当 sink |
| Mattermost 关键操作要重启容器 | 改 ServiceSettings.SiteURL 等 | 已用 `mmctl --local config set` 热改；不需要重启 |
| WSL2 重启后 IP 变 | Windows 重启 | Docker Desktop 自动恢复端口映射，验证后再演示 |
| `+alias` 邮件被 QQ 拒收 | QQ 风控策略变更 | 备选：每个角色独立邮箱（注册 3 个临时邮箱）|
| 面试当天演示网络不通 | 现场断网 / 跨网段 | 提前录视频；本地离线演示包（docker compose 离线镜像）|

---

## 5. 目录最终形态（M5 完成时）

```
hr/
├── PRD.md                           # ✅ v0.3
├── WORK_PLAN.md                     # ✅ 本文档
├── .env / .env.example / .gitignore # ✅
├── README.md                        # M5
├── docs/
│   ├── design.md                    # M5（架构、状态机、API 契约）
│   ├── demo-script.md               # M5
│   └── demo.mp4                     # M5
├── deploy/
│   └── mattermost/                  # ✅
│       ├── README.md
│       ├── .env.example
│       ├── deploy-wsl.sh
│       ├── seed-mattermost.sh
│       └── ACCOUNTS.md
├── tools/                           # M1 工具脚本
│   ├── smtp_ping.py
│   ├── mm_ping.py
│   └── mm_dm.py
├── backend/                         # M2 - M3
│   ├── docker-compose.yml           # postgres + redis + flow-api
│   ├── flow_engine/
│   │   ├── graph.py
│   │   ├── nodes/
│   │   ├── templates/
│   │   └── tests/
│   ├── app/                         # FastAPI
│   │   ├── api/
│   │   ├── auth/
│   │   ├── notification/
│   │   └── integration/
│   └── migrations/
└── web/                             # M4 (Next.js)
    ├── app/
    │   ├── flow/[id]/node/[nid]/
    │   ├── dashboard/
    │   └── timeline/
    └── components/
```

---

## 6. 时间预估（粗）

| 阶段 | 实际工作量（专注小时） | 适合节奏 |
| --- | --- | --- |
| M1 | 1-2 h | 1 个晚上 |
| M2 | 6-8 h | 2 个晚上 |
| M3 | 6-8 h | 2 个晚上 |
| M4 | 8-12 h | 周末 1-2 天 |
| M5 | 4-6 h | 1 个晚上 |

总：约 25-36 工时；如果只交付 Design Doc 不做 demo，砍到 8-12 工时。

---

## 7. 状态更新约定

- 每次结束一个任务，把对应行从 `⏳` 改成 `✅`
- 新发现的问题加到 §3 或 §4
- 真有重大改动（如换技术栈），更新 PRD 的版本号 + 变更日志后回到这里同步
