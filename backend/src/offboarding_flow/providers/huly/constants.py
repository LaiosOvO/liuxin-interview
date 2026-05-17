"""Huly 模型 class id / space id / mixin id 字符串常量。

来源：@hcengineering/{core,chunter,contact,document} 模块的 build('component:name', ...) 注册。
v0.7 这些字符串 ID stable，不会变。如需新增按 colon-separated 命名规则添加：
    {module}:class:{Name}    — Doc 子类
    {module}:mixin:{Name}    — mixin
    {module}:space:{Name}    — system space
    {module}:ids:{Name}      — singleton document id

参考：spike 验证 contact:class:Channel + core:class:TxCreateDoc + core:space:Tx 已 work。
"""

from __future__ import annotations

# ----- core 模块 ------------------------------------------------------------ #

CORE_CLASS_TX_CREATE_DOC = "core:class:TxCreateDoc"
CORE_CLASS_TX_UPDATE_DOC = "core:class:TxUpdateDoc"
CORE_CLASS_TX_REMOVE_DOC = "core:class:TxRemoveDoc"
CORE_CLASS_TX_MIXIN = "core:class:TxMixin"
CORE_CLASS_TX_APPLY_IF = "core:class:TxApplyIf"

CORE_CLASS_DOC = "core:class:Doc"
CORE_CLASS_ATTACHED_DOC = "core:class:AttachedDoc"
CORE_CLASS_SPACE = "core:class:Space"

CORE_SPACE_TX = "core:space:Tx"
CORE_SPACE_DERIVED_TX = "core:space:DerivedTx"
CORE_SPACE_MODEL = "core:space:Model"
CORE_SPACE_SPACE = "core:space:Space"
CORE_SPACE_CONFIGURATION = "core:space:Configuration"

# ----- contact 模块 ---------------------------------------------------------- #

CONTACT_CLASS_PERSON = "contact:class:Person"
CONTACT_CLASS_CONTACT = "contact:class:Contact"
CONTACT_CLASS_SOCIAL_IDENTITY = "contact:class:SocialIdentity"
CONTACT_CLASS_CHANNEL = "contact:class:Channel"

CONTACT_MIXIN_EMPLOYEE = "contact:mixin:Employee"

CONTACT_SPACE_CONTACTS = "contact:space:Contacts"
CONTACT_SPACE_EMPLOYEE = "contact:space:Employee"

CONTACT_CHANNEL_PROVIDER_EMAIL = "contact:channelProvider:Email"

# ----- chunter 模块（messaging）---------------------------------------------- #

CHUNTER_CLASS_DIRECT_MESSAGE = "chunter:class:DirectMessage"
CHUNTER_CLASS_CHANNEL = "chunter:class:Channel"
CHUNTER_CLASS_CHAT_MESSAGE = "chunter:class:ChatMessage"
CHUNTER_CLASS_THREAD_MESSAGE = "chunter:class:ThreadMessage"

# ----- document 模块（Teamspace + Document）--------------------------------- #

DOCUMENT_CLASS_TEAMSPACE = "document:class:Teamspace"
DOCUMENT_CLASS_DOCUMENT = "document:class:Document"

DOCUMENT_IDS_NO_PARENT = "document:ids:NoParent"

# document v0.7.423 缺省 type id（Plan 04 deviation #1 — npm 包不存在，从 server schema 取）
DOCUMENT_TYPE_DEFAULT = "document:ids:DocumentType"

# ----- tracker 模块（Issue / Project）— Plan 7+ 加 ------------------------- #

TRACKER_CLASS_PROJECT = "tracker:class:Project"
TRACKER_CLASS_ISSUE = "tracker:class:Issue"

# ----- 默认值 ---------------------------------------------------------------- #

# Plan 06 seed 所有 demo 用户的 email 域名（与 sidecar im.ts 对齐）
DEMO_EMAIL_DOMAIN = "demo.local"
