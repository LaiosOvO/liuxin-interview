# Huly 平台对接架构 — 文档协作 + IM 双模块改造

> 日期：2026-05-18
> 阶段：Phase 8 / B-full-channel 重构完成
> 范围：离职流程系统与 Huly Platform v0.7.423 的完整对接细节（文档协作 + IM 消息）
> 实施 commit：`2ae8bf8`

---

## 1. 对接目标

替换原有 Outline（文档）+ Mattermost（IM）方案为统一的 Huly Platform：
- **DocProvider**：从 Outline 切换到 Huly Document / Teamspace
- **IMProvider**：从 Mattermost 切换到 Huly chunter
- **IssueProvider**（spike 验证）：业务任务作为 Huly Tracker Issue 分配给责任人
- **会议总结**：MeetingService 输出自动落 Huly Teamspace（业务代码 0 修改）

---

## 2. 两版方案对比

| 维度 | 早期 A 方案（sidecar） | 当前 B-full-channel 方案 |
|---|---|---|
| 进程数 | backend + huly-bridge Node sidecar (2) | backend (1) |
| Tx 链路 | Python → sidecar HTTP → @hcengineering/api-client (TS WS) → transactor | Python → Huly nginx → transactor REST |
| 代码量 | sidecar 约 1200 行 TS | `providers/huly/` 660 行 Python |
| DM 实现 | chunter:DirectMessage | chunter:Channel per user |
| Doc content | 直接传 markdown (UI 不渲染) | 走 collab service markup upload |
| 维护点 | sidecar Dockerfile + Node deps + Huly TS 升级 | Python Tx schema 一处 |
| 部署 | docker-compose 多一个 service | 单容器（需 attach huly_huly_net） |

---

## 3. 完整对接架构

```
┌─────────────────────────────────────────┐         ┌──────────────────────────┐
│ offboarding-flow-api (Python)           │         │ Huly Platform (14 容器)  │
│                                         │         │                          │
│ providers/huly/                         │         │ nginx :8087              │
│ ┌─────────────────────────────────┐     │         │ ├─ /                  → │
│ │ rest_client.py                  │     │         │ │  front (HTML/JS UI)    │
│ │   POST {accounts_url}           │ ──→ │ HTTP    │ ├─ /_accounts/        → │
│ │     login / selectWorkspace     │     │         │ │  account-1 :3000 (RPC)│
│ │   GET  /api/v1/account/{ws}     │     │         │ ├─ /_transactor/      → │
│ │   GET  /api/v1/find-all/{ws}    │ ──→ │ HTTP    │ │  transactor-1 :8080  │
│ │   POST /api/v1/tx/{ws}          │     │         │ │  (REST + WS)         │
│ │   POST /api/v1/ensure-person/.. │     │         │ ├─ /_stats/           → │
│ └─────────────────────────────────┘     │         │ │  stats-1 :4900       │
│                                         │         │ └─ /_kvs/             → │
│ ┌─────────────────────────────────┐     │         │    kvs-1 :8094         │
│ │ tx_factory.py + tx_operations.py│     │         │                          │
│ │   TxCreateDoc / TxCollectionCUD │     │         │ collaborator :3078       │
│ │   TxUpdateDoc / TxRemoveDoc     │     │         │ ├─ /rpc/{docId}       ←─┼── 直接 HTTP（需 docker network connect）
│ │   ProseMirror → Markup ref      │     │         │ │   getContent /         │
│ └─────────────────────────────────┘     │         │ │   createContent /      │
│                                         │         │ │   updateContent        │
│ huly_doc_provider.py                    │         │                          │
│ huly_im_provider.py                     │ ──→ docker network: │ 内部互通      │
│   ↑                                     │     huly_huly_net   │              │
│   依赖 IM_PROVIDER=huly / DOC_PROVIDER=huly  └────────────────┘              │
└─────────────────────────────────────────┘         └──────────────────────────┘
```

---

## 4. 文档协作对接（HulyDocProvider）

### 4.1 数据模型映射

| 业务概念 | Outline 对应 | Huly 对应 |
|---|---|---|
| collection（员工独立空间） | Collection | `document:class:Teamspace`（space 类型） |
| document（节点文档） | Document | `document:class:Document`（attachedTo=Teamspace） |
| owner / members | collection.permissions | space.owners / space.members（PersonUuid 列表） |

### 4.2 创建 Teamspace 流程

```python
# providers/huly_doc_provider.py:HulyDocProvider.create_collection
space_id = await pc.ops.create_doc(
    DOCUMENT_CLASS_TEAMSPACE,        # "document:class:Teamspace"
    CORE_SPACE_SPACE,                # "core:space:Space" (system space for Spaces)
    {
        "name": "离职 · it.charlie",
        "description": "离职归档",
        "private": False,
        "archived": False,
        "members": [bot_uuid, employee_uuid],  # 来自 SocialIdentity → Employee mixin
        "owners":  [employee_uuid],
        "autoJoin": False,
        "type": "document:ids:DocumentType",
    },
)
# → 内部合成 TxCreateDoc → POST /api/v1/tx/{ws} → server 写入 transactor doc store
```

### 4.3 创建 Document 流程（含 content 真实渲染）

**关键发现**：Huly Document 的 `content` 字段不是 raw markdown，而是 **collab service 的 blob reference**（格式 `{docId}-content-{timestamp}`）。简单字符串写入会被 server 接受但 UI 不渲染。

完整流程（2 步）：

```python
# Step 1: 创 doc shell（content 暂为空 / 临时 string）
doc_id = await pc.ops.create_doc(
    DOCUMENT_CLASS_DOCUMENT,
    teamspace_id,                    # space = Teamspace _id
    {
        "title": "03 - it_asset · IT 资产回收",
        "content": "",                # 临时占位
        "parent": "document:ids:NoParent",
        "rank": str(int(time.time() * 1000)),
    },
)

# Step 2: 上传 markup 到 collab service 拿 ref，然后 update doc.content
import urllib.parse, httpx, json
ws_uuid = pc.rest.workspace_uuid
encoded_doc_id = urllib.parse.quote(
    f"{ws_uuid}|{DOCUMENT_CLASS_DOCUMENT}|{doc_id}|content",  # 结构：workspace|class|objectId|attr
    safe="",
)
markup = json.dumps({
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "IT 资产回收清单"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": 'MacBook Pro 14"'}]}]},
            # ... 更多 list item
        ]},
    ],
}, ensure_ascii=False)
async with httpx.AsyncClient(timeout=10) as c:
    r = await c.post(
        f"http://collaborator:3078/rpc/{encoded_doc_id}",
        json={"method": "createContent", "payload": {"content": {"content": markup}}},
        headers={"Authorization": f"Bearer {ws_token}"},
    )
ref = r.json()["content"]["content"]
# ref 形如 "af485c177e7a395e4c928413-content-1779040333023"
await pc.ops.update_doc(DOCUMENT_CLASS_DOCUMENT, teamspace_id, doc_id, {"content": ref})
```

### 4.4 网络配置（关键前置）

backend 容器默认只在 `offboarding-flow_offboarding-net`，要调到 huly stack 的 collaborator service 必须：

```bash
docker network connect huly_huly_net offboarding-flow-api
# 之后 backend 内 http://collaborator:3078 可达
```

或写入 `docker-compose.yml`：

```yaml
services:
  flow-api:
    networks:
      - offboarding-net
      - huly_huly_net  # 新增

networks:
  huly_huly_net:
    external: true     # 复用 huly stack 创建的网络
```

### 4.5 collab service RPC 协议（关键参考）

来源：`@hcengineering/collaborator-client/src/client.ts`

- URL：`POST {collaboratorUrl}/rpc/{urlEncoded(documentId)}`
- documentId 结构：`{workspaceUuid}|{objectClass}|{objectId}|{objectAttr}`
- Body：`{method: "getContent" | "createContent" | "updateContent", payload: {...}}`
- Headers：`Authorization: Bearer {workspaceToken}`
- createContent payload：`{content: {[objectAttr]: markup}}` → 返回 `{content: {[objectAttr]: blobRef}}`
- markup 是 Huly 内部 markup 字符串（即 ProseMirror JSON 的 stringify）

### 4.6 现有 DocProvider 行为对照

| 接口方法 | Outline 实现 | Huly 实现 |
|---|---|---|
| `create_collection(name, owner)` | POST /api/collections.create | `ops.create_doc(Teamspace, ...)` |
| `create_document(title, markdown, collection)` | POST /api/documents.create（markdown 直接 import） | `ops.create_doc(Document)` + collab `createContent` + `update_doc(content=ref)` |
| `get_document(doc_id)` | GET /api/documents.info | `rest.find_one(Document, {_id})` |
| `list_documents_in_collection` | POST /api/documents.list | `rest.find_all(Document, {space=collection_id})` |
| `delete_document(doc_id)` | POST /api/documents.delete | `ops.remove_doc(Document)` |
| `delete_collection(id)` | POST /api/collections.delete | 列 docs + 逐个 remove + remove Teamspace |

---

## 5. IM 对接（HulyIMProvider）

### 5.1 数据模型映射

| 业务概念 | Mattermost 对应 | Huly 对应 |
|---|---|---|
| 私聊 DM | Direct Message channel (D 类型) | **chunter:Channel** (per-user，命名 `dm-{username}`) |
| 公共频道 | Channel (O 类型) | `chunter:Channel`（多 members） |
| 消息 | Post | `chunter:ChatMessage`（AttachedDoc 挂在 Channel.messages collection） |
| 用户身份 | user_id | PersonUuid（通过 SocialIdentity → Employee mixin 解析） |

### 5.2 关键设计：DM 降级为「per-user Channel」

**spike 发现**：新建 `chunter:DirectMessage` 后立即 add ChatMessage 在 server 端 server 静默 reject（不写入 DB，但 Tx 提交 200 OK）— 推测是新建 DM 的 ACL/join 事件未与 collab service 完全同步。

**绕开方案**：DM 实现改为「每员工一个 chunter:Channel」+ bot 和 employee 都是 members。Channel + ChatMessage 这条路径 server 立即接受写入（spike5 已验证）。

业务影响：
- 仍是 IM 体验（消息可见性 = DM 体验）
- HR demo 反而更直观（HR 一个频道列表看所有员工流程进度）

### 5.3 send_dm 完整流程

```python
# providers/huly_im_provider.py:HulyIMProvider.send_dm
async def send_dm(self, username, markdown):
    pc = await self._ensure_client()

    # Step 1: ensure_user_channel — 找/创 dm-{username} channel
    channel_name = f"dm-{username}"
    ch = await pc.rest.find_one(CHUNTER_CLASS_CHANNEL, {"name": channel_name})
    if ch is None:
        bot = pc.bot_account
        target = await self._resolve_account(pc, username)  # SocialIdentity → Employee → personUuid
        members = [bot] + ([target] if target else [])
        channel_id = await pc.ops.create_doc(
            CHUNTER_CLASS_CHANNEL,
            CORE_SPACE_SPACE,
            {
                "name": channel_name,
                "description": f"离职流程私聊频道 — {username}",
                "private": True,
                "archived": False,
                "members": members,
                "autoJoin": False,
            },
        )
    else:
        channel_id = ch["_id"]

    # Step 2: add_collection ChatMessage（核心 — 走 TxCollectionCUD）
    await pc.ops.add_collection(
        CHUNTER_CLASS_CHAT_MESSAGE,
        channel_id,           # space = Channel._id
        channel_id,           # attached_to = Channel._id
        CHUNTER_CLASS_CHANNEL,  # attached_to_class
        "messages",            # collection name（chunter Channel 的 messages 字段）
        {"message": markdown, "attachments": 0},
    )
```

### 5.4 add_collection 内部 Tx 结构

`TxCollectionCUD` 不是单独的 Tx 类，而是在 inner `TxCreateDoc` 上 spread 3 字段：

```python
# tx_factory.py:create_tx_collection_cud
{
    # inner TxCreateDoc 的所有字段
    "_id": ..., "_class": "core:class:TxCreateDoc",
    "space": "core:space:Tx",
    "objectId": ..., "objectClass": "chunter:class:ChatMessage",
    "objectSpace": channel_id,
    "attributes": {"message": "...", "attachments": 0},
    "modifiedBy": bot_account, ...
    # 加 3 字段：
    "collection": "messages",
    "attachedTo": channel_id,
    "attachedToClass": "chunter:class:Channel",
}
```

### 5.5 PersonUuid 解析（SocialIdentity → Employee）

业务侧使用 `username` 标识员工（如 "it.charlie"），Huly 内部用 `PersonUuid`。映射规则（沿用 sidecar 时代）：

```python
async def _resolve_account(pc, username):
    # 1. find SocialIdentity by key
    social_key = f"email:{username}@demo.local"   # PRD §9.1.3 demo 域名约定
    si = await pc.rest.find_one("contact:class:SocialIdentity", {"key": social_key})
    if not si:
        return None
    # 2. find Employee mixin by id (mixin _id 等于 PersonId)
    emp = await pc.rest.find_one("contact:mixin:Employee", {"_id": si["attachedTo"]})
    return emp.get("personUuid") if emp else None
```

13 个业务用户需通过 `scripts/seed_huly_users.py` 离线 seed 到 Huly（创 Person + SocialIdentity + Employee mixin）。未 seed 时 `_ensure_user_channel` 仍创 channel（只 bot 是 member），消息可发但目标用户看不到。

### 5.6 IMProvider 行为对照

| 接口方法 | Mattermost 实现 | Huly 实现 |
|---|---|---|
| `send_dm(username, markdown)` | POST /api/v4/users/me/posts (DM channel) | ensure dm-{username} channel + add_collection ChatMessage |
| `post_to_channel(channel_id, md)` | POST /api/v4/posts | add_collection ChatMessage |
| `ensure_user_in_channel(...)` | POST /api/v4/channels/{id}/members | find Channel → update_doc `{$push: {members: target}}` |
| `list_team_users()` | GET /api/v4/teams/{id}/members | 业务 DB users 表 source of truth（不查 Huly） |
| `resolve_username(...)` | GET /api/v4/users/{username} | 返回占位 UserInfo（业务 DB 才是真实来源） |

---

## 6. Tracker Issue 对接（spike 验证）

未在 v1 Provider 抽象内，但 Python REST 已验证可达。业务场景：离职流程 5 个并行任务作为 Tracker Issue 分给责任人。

```python
# spike: 创 Issue 分给 bot
issue_id = await pc.ops.create_doc(
    TRACKER_CLASS_ISSUE,                  # "tracker:class:Issue"
    project_id,                            # space = Project _id（每个 Project 是自己的 space）
    {
        "title": "[it.charlie] IT 资产回收 — MacBook/显示器/工卡",
        "description": "...",
        "assignee": bot_account_uuid,      # PersonUuid
        "status": "tracker:status:Backlog",
        "priority": 2,                     # Medium
        "number": 42, "rank": str(now),
        "estimation": 0, "remainingTime": 0,
        "kind": "tracker:taskTypes:Issue",
        "identifier": "GAME-42",
    },
)
```

后续 v2 加 `IssueProvider` Protocol + `HulyIssueProvider` 实现，业务节点输出（如 IT 资产回收清单）转 Tracker Issue 自动分给责任人。

---

## 7. 会议总结对接（业务代码 0 修改）

`services/meeting_service.py:838` 已用 `doc_provider.create_document(...)` 抽象调用。当 `DOC_PROVIDER=huly` 时自动走 HulyDocProvider，会议总结落 Huly Teamspace（无需任何业务代码修改）。

```python
# meeting_service.py 现有代码
doc_info: DocInfo = await doc_provider.create_document(
    title=meeting_title,
    markdown=summary_md,
    owner_usernames=[organizer],
    collection_name=collection_id,
)
```

verified：通过 `docker exec offboarding-flow-api python /tmp/huly_e2e_inside.py` 实测会议 doc 真落 Huly。

---

## 8. config 字段对照

### 8.1 删除的 config（sidecar 时代）

```python
# 已废弃
huly_bridge_url: str = "http://huly-bridge:7777"
huly_bridge_token: str = ""
huly_bridge_http_timeout: float = 15.0
huly_bot_account_uuid: str = ""
```

### 8.2 新增的 config（B-full）

```python
# config.py
huly_url: str = "http://192.168.2.44:8087"          # Huly Front + nginx 入口
huly_accounts_url: str = "http://192.168.2.44:8087/_accounts"  # Account RPC
huly_workspace: str = "laios"                        # workspace URL name
huly_admin_email: str = ""                           # admin 邮箱（已有 SocialIdentity 的账号）
huly_admin_password: str = ""                        # admin 密码（敏感，仅 .env）
huly_user_channel_prefix: str = "dm-"                # per-user channel 命名前缀
huly_http_timeout: float = 15.0
```

### 8.3 docker-compose.yml 改动

```yaml
# 删除
services:
  huly-bridge:  # 整段删除
    profiles: ["huly"]
    build: ./backend/sidecars/huly-bridge
    # ...

# 新增（推荐）
services:
  flow-api:
    networks:
      - offboarding-net
      - huly_huly_net   # 新加，必须 attach huly stack 网络才能调 collaborator

networks:
  huly_huly_net:
    external: true       # 复用 huly stack 创建的网络
```

---

## 9. 已知问题与后续工作

| 问题 | 现状 | 应对 |
|---|---|---|
| DM (`chunter:DirectMessage`) | 新建 DM 后立即 add ChatMessage server 静默 reject | 改用 per-user `chunter:Channel` 绕开（B-full-channel） |
| HulyListener 反向接收消息 | v1 stub（不接收 user @bot） | 后续补 polling 模式：每 10s 查 dm-* channel 新 ChatMessage 触发 dispatch |
| Issue 分配 | 仅 spike 验证可达，无 Provider 抽象 | 加 `IssueProvider` Protocol + `HulyIssueProvider` 实现 |
| HulyDocProvider.create_document 当前只创 doc shell | content 字段需手动调 collab service 才显示 | 升级 Provider 内置 collab upload（合并到 `create_document` 一次调用完成） |
| Huly chunter 浏览器 console 报 `Unexpected token '<'` | nginx 未配 `/_collaborator/` proxy | 影响实时同步（不影响 backend 写入），可补 nginx config |
| 用户 seed | demo 用户身份手动 seed | `scripts/seed_huly_users.py` 完善后自动化 |
| sidecar 目录归档 | `backend/sidecars/huly-bridge/` 保留作历史参考 | 确认稳定 1 周后删 |

---

## 10. 文档关联

- `docs/huly-e2e-test-2026-05-18.md` — 当前完整 E2E 测试报告（含 browser-harness 截图）
- `docs/offboarding-e2e-test-2026-05-17-final.md` — 离职流程基线 E2E（前 sidecar 时代）
- `docs/meeting-summary-e2e-test-2026-05-17.md` — 会议总结 E2E
- `docs/reading-huly-platform-2026-05-17.md` — Huly Platform 架构调研

---

*实施 commit: 2ae8bf8 / 文档更新: 2026-05-18*
