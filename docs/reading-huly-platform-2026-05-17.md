# Huly Platform 阅读笔记（telegram-bot / ai-bot / huly-mcp）

> 日期: 2026-05-17
> 仓库: hcengineering/huly (clone 到 ~/ai/ref/agent/huly/)
> 用于: Phase 8 Plan 05 — huly-bridge sidecar 业务路由真实现 + Python provider 反向 webhook

## 项目概述

Huly 是开源协作平台（issue tracker + chat + wiki + drive），TS SDK 走 `@hcengineering/*` 系列包；
本次阅读 `services/telegram-bot`、`services/ai-bot`、`huly-mcp` 三个生产级实现，提取
sidecar 业务路由 + 反向 chat 订阅模式。

## 技术栈关键点

- `@hcengineering/api-client` `connect(url, {token, workspace})` → `PlatformClient`
- `@hcengineering/core` `core.space.Space`（DM / Channel 父空间）+ `core.space.Workspace`
- `@hcengineering/chunter` `chunter.class.DirectMessage` / `chunter.class.Channel` / `chunter.class.ChatMessage`
- `@hcengineering/contact` `contact.class.SocialIdentity { key: 'email:{user}@demo.local' }` 查 PersonId
- `@hcengineering/contact` `contact.mixin.Employee { _id: socialId.attachedTo }` 拿 `personUuid` (= AccountUuid)
- `@hcengineering/server-token` `generateToken(systemAccountUuid, undefined, {service:'offboarding-bot'})`

## 可借鉴的设计模式

### 1. socialKey + Employee 解 AccountUuid（canonical 实现）

文件：`~/ai/ref/agent/huly/services/ai-bot/pod-ai-bot/src/utils/platform.ts:26-36`

```typescript
export async function getAccountBySocialKey (client, socialKey): Promise<AccountUuid | null> {
  const socialIdentity = await client.findOne(contact.class.SocialIdentity, { key: socialKey })
  if (socialIdentity == null) return null
  const employee = await client.findOne(contact.mixin.Employee, {
    _id: socialIdentity.attachedTo as Ref<Employee>
  })
  return employee?.personUuid ?? null
}
```

**应用到 Plan 05**：
- sidecar 的 `resolveAccountByUsername(client, username)` 走 `socialKey: 'email:{username}@demo.local'`
- Plan 06 seed_huly_users.py 创 user 时 SocialIdentity.key 用同样模式

### 2. 查/建 DM 模式（findAll → match → createDoc fallback）

文件：`~/ai/ref/agent/huly/services/ai-bot/pod-ai-bot/src/utils/platform.ts:38-76`

```typescript
const existingDm = (await client.findAll(chunter.class.DirectMessage, { members: aibotAccount }))
  .find((dm) => dm.members.every((m) => m === aibotAccount || m === account))

if (existingDm !== undefined) return existingDm._id

const dmId = await client.createDoc<DirectMessage>(chunter.class.DirectMessage, core.space.Space, {
  name: '', description: '', private: true, archived: false,
  members: [aibotAccount, account]
})
```

**应用到 Plan 05**：sidecar `POST /api/im/send_dm` 复制此 pattern；DM 父空间是 `core.space.Space`。

### 3. ChatMessage addCollection 模式

文件：`~/ai/ref/agent/huly/services/ai-bot/pod-ai-bot/src/controller.ts:254-330`
和：`~/ai/ref/agent/huly/services/ai-bot/pod-ai-bot/src/workspace/workspaceClient.ts:369-380`

```typescript
await op.addCollection(
  chunter.class.ChatMessage,
  dmId,            // space = dm 自己
  dmId,            // attachedTo
  chunter.class.DirectMessage,
  'messages',
  { message: markdown, attachments: 0 },
  generateId()
)
```

**应用到 Plan 05**：sidecar `POST /api/im/send_dm` 第 2 步 / `POST /api/im/post_channel` 同样 pattern。

### 4. Service Token 模式（已 Plan 04 实现）

文件：`~/ai/ref/agent/huly/services/telegram-bot/pod-telegram-bot/src/utils.ts`

```typescript
generateToken(systemAccountUuid, undefined, { service: 'telegram-bot-service' })
```

**已应用**：Plan 04 `src/auth.ts:serviceToken()`。

### 5. 反向 chat 订阅 — 2s poll 模式（v1 简单）

参考：`~/ai/ref/agent/huly/services/telegram-bot/pod-telegram-bot/src/worker.ts` 框架；
Plan 05 RESEARCH §Open Questions #2 已确定先用 poll。

```typescript
let lastSeen = Date.now()
setInterval(async () => {
  const msgs = await client.findAll(
    chunter.class.ChatMessage,
    { createdOn: { $gt: lastSeen } },
    { sort: { createdOn: 1 }, limit: 100 }
  )
  for (const msg of msgs) {
    if (msg.modifiedBy === botAccountUuid) continue  // Pitfall #6 死循环防护
    lastSeen = Math.max(lastSeen, msg.createdOn)
    await fetch(`${backendUrl}/api/internal/huly/event`, {
      method: 'POST',
      headers: { 'X-Bridge-Token': bridgeToken },
      body: JSON.stringify({ ...payload })
    })
  }
}, 2000)
```

**应用到 Plan 05**：sidecar `src/listener.ts` 实现这个 pattern；v2 升级 live 订阅（暂不考虑）。

### 6. Pitfall 防御

- **死循环防护**（必须）：listener poll 出的消息若 `modifiedBy === botAccountUuid` 立即跳过
- **lastSeen 单调**：用 `Math.max(lastSeen, msg.createdOn)` 防止时间倒退
- **fetch 失败 silent**：reverse webhook 失败仅 log，不阻塞 poll 循环

## 与本项目的关系

| 文件 | 用途 |
|------|------|
| `backend/sidecars/huly-bridge/src/im.ts` (Plan 05 Task 1) | 复用 socialKey resolver + DM 查建 + ChatMessage addCollection |
| `backend/sidecars/huly-bridge/src/listener.ts` (Plan 05 Task 2) | 复用 2s poll + 死循环防护模式 |
| `backend/sidecars/huly-bridge/src/doc.ts` (Plan 05 Task 2) | 用 `document.class.Teamspace` + `document.class.Document`（huly-mcp 参考） |
| `backend/src/offboarding_flow/providers/huly_*.py` (Plan 05 Task 3) | 通过 httpx 调 sidecar `/api/im/*` `/api/doc/*` |
| `backend/src/offboarding_flow/api/internal_huly.py` (Plan 05 Task 3) | 接 sidecar 反向 webhook，BRIDGE_TOKEN 鉴权 |

## 注意事项

- `@hcengineering/document` 在 npm 公网只有 0.7.0（Plan 04 deviation #1 已记）；本 plan 用 chunter.Card 兜底或暂仅模拟 doc 路由
- `@hcengineering/api-client` 的 `connect()` 返回的 PlatformClient 与上面 `Client / TxOperations` 接口一致，可直接复用
- BotAccountUuid 在 Plan 05 启动期通过 `systemAccountUuid`（常量）作为 listener 死循环防护标识；Plan 06 seed_huly_users 后可换成真实 bot account UUID

---

## 追加 — Plan 06 / HULY-08（seed 路径 admin token + signUpJoin）

> 日期: 2026-05-17（晚段追加）
> 用途: Phase 8 Plan 06 — `scripts/seed_huly_users.py` + `sidecar/src/admin.ts`

### 7. 避开 createInviteLink autoJoin Forbidden（Pitfall #1 — verifyAllowedServices）

文件源码定位（已查）：
- `~/ai/ref/agent/platform/server/account/src/operations.ts`（createInviteLink 内 verifyAllowedServices 仅放行 `service='schedule'`）

**后果**：service token（systemAccountUuid + service='offboarding-bot'）调 createInviteLink(autoJoin=true) 返回 Forbidden。

**绕过方案**（Plan 06 实现）：
1. 不用 createInviteLink；改用 admin token（真人 login 拿）调 `createInvite(exp, emailMask, limit, role)` — 普通 invite 不受 verifyAllowedServices 拦截
2. 用 anonymous client 调 `signUpJoin(email, password, first, last, inviteId, workspaceUrl)` — 公开 endpoint，一步完成「注册账号 + 加 workspace」

### 8. signUpJoin 完整签名

文件：`backend/sidecars/huly-bridge/node_modules/@hcengineering/account-client/src/client.ts:566-580`

```typescript
async signUpJoin (
  email: string,
  password: string,
  first: string,
  last: string,
  inviteId: string,
  workspaceUrl: string
): Promise<WorkspaceLoginInfo>
```

返回 `{account, token, workspace, workspaceUrl, endpoint}` — `account` 字段就是 AccountUuid（与 socialKey resolver 拿到的同源）。

### 9. getAccountClient(accountsUrl, token) factory

文件：`backend/sidecars/huly-bridge/node_modules/@hcengineering/account-client/src/client.ts:268-275`

```typescript
export function getClient(accountsUrl?: string, token?: string, retryTimeoutMs?: number): AccountClient
```

- `token === undefined` → 匿名 client（用于 signUp / signUpJoin / 公开 endpoint）
- `token === adminToken` → 管理员 client（用于 createInvite / createWorkspace）

### 10. 幂等策略

Plan 06 `handleSignUpJoin` 兜底逻辑：
1. signUpJoin 失败且 error message 含 "already exists" / "duplicate" → 走 login 拿 accountUuid → 返回 `{skipped: true}`
2. login 也失败 → 返回 409 ACCOUNT_EXISTS_PASSWORD_MISMATCH（密码不一致需人工介入）
3. signUpJoin 失败非已存在 → 400 SIGNUP_JOIN_FAILED 透传错误

这样脚本重跑 100% 幂等。

### 11. 双 token 鉴权（CLAUDE.md §3.5 凭证安全）

- BRIDGE_TOKEN：Python backend ↔ sidecar 常规通信（IM / Doc / listener webhook 都用）
- ADMIN_TOKEN：admin 路由的「第二道」保护（仅 seed 脚本注入），防 LLM 通过 BRIDGE_TOKEN 调 admin 路由污染 Huly 账号数据

实现：`sidecar/src/middleware.ts:adminAuth(expectedToken)` 中间件叠在 bridgeAuth 之后。

---

*为 Phase 8 Plan 05 编写；Plan 06 在 §7-§11 追加 admin/signUpJoin 实现要点。*
