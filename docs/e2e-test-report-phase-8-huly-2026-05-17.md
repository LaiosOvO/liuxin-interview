# Phase 8 Plan 06 E2E 测试报告 — Huly IM 流程验收

> 日期: 2026-05-17
> Phase: 8B Huly Abstraction / Plan 06
> 测试 spec: `frontend/tests/e2e/huly_im_flow.spec.ts`
> 状态: **scaffold** — 实际执行待真实 Huly 环境就绪后由 orchestrator 跑

---

## 1. 测试目标

模拟真实用户场景，验证 IM_PROVIDER=huly 切换后端到端通路：

```
it.charlie 浏览器登录 Huly UI
    ↓
找到与 offboarding-bot 的 DM
    ↓
发送"我要离职"
    ↓
[sidecar listener] 2s poll 拿到新消息
    ↓
[sidecar] POST /api/internal/huly/event (X-Bridge-Token)
    ↓
[backend HulyListener] handle_webhook
    ↓
[BotService] dispatch start 命令
    ↓
创建 flow_instance + 节点 + 通知
    ↓
[HulyIMProvider] post_to_channel 回写"流程已启动"
    ↓
[sidecar im.ts] addCollection ChatMessage
    ↓
Huly UI 显示 bot 回复 ✓
```

## 2. 前置环境

| 服务 | 版本 | 地址 |
|------|------|------|
| Huly Front | v0.7.423 | http://192.168.2.44:8087 |
| Huly Accounts | v0.7.423 | http://192.168.2.44:3007 |
| Huly Transactor | v0.7.423 | ws://192.168.2.44:3333 |
| huly-bridge sidecar | 0.1.0 | http://huly-bridge:7777 |
| offboarding-backend | 0.1.0 | http://192.168.2.44:8000 |
| offboarding-postgres | 16 | offboarding-postgres:5432 |

容器清单（启动顺序）：
1. `docker compose up -d` — 5 个核心 service
2. `docker compose --profile huly-stack up -d` — 14 个 Huly 容器
3. `docker compose --profile huly up -d huly-bridge` — sidecar

种子数据：
1. `scripts/seed_demo_data.py` — 业务 DB 13 个 user + 5 个 team
2. `scripts/seed_huly_users.py` — 把 13 user 同步到 Huly workspace `laios`

切换配置：
- `.env` 改 `IM_PROVIDER=huly` + `DOC_PROVIDER=huly`
- `docker compose restart backend`

## 3. 测试步骤

### Step 1 — 打开 Huly 登录页

**操作:** `page.goto('http://192.168.2.44:8087')`

**期望:**
- 页面 200 加载
- 显示登录表单

**截图:** `docs/screenshots/huly-flow-1-login.png`

**结果:** [待执行]

### Step 2 — it.charlie 登录

**操作:**
- 填 email: `it.charlie@demo.local`
- 填 password: `<HULY_USER_PASSWORD>`
- 点击登录

**期望:**
- 跳到主界面
- 左侧 sidebar 显示 Direct Messages

**截图:** `docs/screenshots/huly-flow-2-loggedin.png`

**结果:** [待执行]

### Step 3 — 打开与 offboarding-bot 的 DM

**操作:** 点击左侧 DM 列表中的 `offboarding-bot`

**期望:**
- 进入与 bot 的私聊界面
- 显示消息输入框

**截图:** `docs/screenshots/huly-flow-3-dm-opened.png`

**结果:** [待执行]

### Step 4 — 发送"我要离职"

**操作:**
- 在消息输入框输入"我要离职"
- 按 Enter 发送

**期望:**
- 消息出现在聊天历史中

### Step 5 — 等待 bot 回复

**操作:** 等待最多 15s

**期望:**
- bot 回复"您的离职流程已创建…" 或 "流程已启动…"
- 时间窗口：2s (sidecar poll) + 1s (dispatch) + 1s (回写) = ~4s

**截图:** `docs/screenshots/huly-flow-4-bot-reply.png`

**结果:** [待执行]

### Step 6 — 验证业务 DB

**操作:**
```bash
docker exec offboarding-postgres psql -U offboarding -d offboarding -c \
  "SELECT id, employee_id, status, created_at FROM app.flow_instances \
   WHERE employee_id='it.charlie' ORDER BY created_at DESC LIMIT 3"
```

**期望:** 至少 1 行新流程，`status='in_progress'`

**截图:** `docs/screenshots/huly-flow-6-flow-instance.png`

**结果:** [待执行]

### Step 7 — backend 日志验证（辅助）

**操作:**
```bash
docker compose logs backend | grep -E "dispatch_message|HulyListener|/api/internal/huly/event"
```

**期望:** 看到 dispatch_message 被调用 + HulyListener.handle_webhook + 节点创建日志

**截图:** `docs/screenshots/huly-flow-5-backend-log.png`

**结果:** [待执行]

---

## 4. Tool 调用链路图

```
[it.charlie 浏览器] (Step 1-4)
        ↓ ↓ ↓
        ↓ HTTPS
[Huly Front :8087] → [Huly Transactor :3333] → 写 chunter.ChatMessage
                                                       ↑
                                              [sidecar listener.ts]
                                              2s poll findAll
                                                       ↓ 新消息
                                              [processOneMessage]
                                              跳 modifiedBy === botAccountUuid
                                                       ↓
                                              [fetch POST /api/internal/huly/event]
                                              X-Bridge-Token header
                                                       ↓
[backend FastAPI /api/internal/huly/event] BRIDGE_TOKEN 鉴权 (Plan 05)
                                                       ↓ 200
[HulyListener.handle_webhook] (Plan 05)
                                                       ↓ 构造 IMHelpers
[dispatch_message] (Plan 01)
                                                       ↓ parse_command "我要离职"
                                                       ↓ → start handler
[BotService.dispatch] (Plan 01)
                                                       ↓ 创建 FlowInstance + NodeState
                                                       ↓ commit 业务表
                                                       ↓
[helpers.send_dm("您的离职流程已创建...")]
                                                       ↓
[HulyIMProvider.send_dm] (Plan 05)
                                                       ↓ httpx POST sidecar
[sidecar /api/im/send_dm] (Plan 05)
                                                       ↓
[im.ts: ensureDirectMessage + addChatMessage]
                                                       ↓ Huly TS SDK
[Huly Transactor] addCollection chunter.ChatMessage
                                                       ↓ 同步到所有 client
[it.charlie 浏览器看到 bot 回复] (Step 5)
```

---

## 5. 已知 selector 适配点

Huly v0.7.423 UI 的 selector 可能与本 spec 不同，首次跑前需用 `npx playwright codegen http://192.168.2.44:8087` 探测：

| Step | 当前 selector（spec 中） | 可能需调整 |
|------|---------|------|
| 2 | `input[type="email"]` | Huly UI 可能用 `input.email` 或自定义组件 |
| 2 | `button[type="submit"]` | Huly UI 用 svelte 组件 |
| 3 | `text=offboarding-bot` | 可能 nested 在更深 component |
| 4 | `[contenteditable="true"]` | Tiptap chat editor |
| 5 | `text=/流程已启动\|您的离职流程已创建/i` | 取决于 bot 实际回复模板 |

---

## 6. 结论

**实际状态:** spec 已写，scaffolding 完成；待真实 Huly stack 启动后由 orchestrator 跑通：

- [ ] Step 1 — 登录页加载
- [ ] Step 2 — 登录成功
- [ ] Step 3 — DM 打开
- [ ] Step 4 — 发送消息
- [ ] Step 5 — bot 回复（关键验收点）
- [ ] Step 6 — DB 写入
- [ ] Step 7 — backend log

**完成方式（orchestrator 后续补）:**
1. 启 Huly stack：`docker compose --profile huly-stack up -d`
2. 等 14 容器 ready（约 60s）
3. 在 Huly UI 手动建 workspace `laios` 并创建 admin 账号
4. 注入 `.env` 真实 HULY_ADMIN_*
5. 跑 `scripts/seed_huly_users.py` 一次成功 + 二次幂等
6. 切 `IM_PROVIDER=huly` 重启 backend
7. 跑 `cd frontend && HULY_URL=... HULY_USER_PASSWORD=... BACKEND_URL=... npx playwright test tests/e2e/huly_im_flow.spec.ts --headed`
8. 截图自动落 `docs/screenshots/`
9. 把"待执行"标记替换为实际结果

---

## 7. 回滚验证（可选加分）

切回 Mattermost 后用同样的 zhang.san 起流程 → 应该 0 影响：

```bash
sed -i '' 's/^IM_PROVIDER=huly/IM_PROVIDER=mattermost/' .env
docker compose restart backend

# 在 MM 中以 zhang.san 对 bot 发"我要离职" → 同样应回复"流程已启动"
```

---

*本报告 scaffold 由 Plan 06 执行器生成；真实 E2E 待 Huly 环境就绪后补完。*
