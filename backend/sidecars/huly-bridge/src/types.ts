/**
 * huly-bridge sidecar — 共享类型定义
 *
 * Phase 8 / HULY-03
 *
 * 本文件定义 sidecar 内部 / API 边界共用的 TypeScript 类型。
 * 业务路由（IM / Doc）的请求 / 响应 schema 在 Plan 05 添加。
 */

/**
 * 解析后的运行时配置（来自 env vars）。
 * 创建后不可变（immutable）。
 */
export interface BridgeConfig {
  /** sidecar 监听端口（默认 7777） */
  readonly port: number
  /** Python backend → sidecar 鉴权 token */
  readonly bridgeToken: string
  /** Huly transactor URL（如 http://192.168.2.44:8087） */
  readonly hulyUrl: string
  /** Huly accounts API URL（如 http://192.168.2.44:3007） */
  readonly hulyAccountsUrl: string
  /** 目标 workspace 名（如 "laios"） */
  readonly hulyWorkspace: string
  /** Huly stack 共享 SERVER_SECRET（与 huly-account 同值） */
  readonly serverSecret: string
  /** Plan 06 反向 listener 用 — backend URL */
  readonly backendUrl: string
  /** 日志级别（debug / info / warn / error） */
  readonly logLevel: LogLevel
  /** 服务名（用于 service token extra.service） */
  readonly serviceName: string
  /** Plan 06: admin API 鉴权 token（第二道保护，仅 seed 脚本用） */
  readonly adminToken: string
  /** Plan 06: Huly admin 邮箱（seed 脚本调 login 拿真人 admin token） */
  readonly adminEmail: string
  /** Plan 06: Huly admin 密码（seed 脚本调 login） */
  readonly adminPassword: string
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

/**
 * 标准化错误响应（所有 endpoint 返回失败时的统一格式）。
 *
 * 与 Python backend 的 APIResponse envelope 风格对齐。
 */
export interface ErrorResponse {
  readonly ok: false
  readonly error: string
  readonly code?: string
  readonly details?: Record<string, unknown>
}

/**
 * 标准化成功响应。
 */
export interface SuccessResponse<T = unknown> {
  readonly ok: true
  readonly data: T
}

export type ApiResponse<T = unknown> = SuccessResponse<T> | ErrorResponse

/**
 * /healthz 响应 schema。
 */
export interface HealthzResponse {
  readonly ok: true
  /** sidecar 启动后是否成功连上 Huly */
  readonly huly_connected: boolean
  /** sidecar 版本（package.json version） */
  readonly version: string
  /** 当前进程 uptime（秒） */
  readonly uptime: number
  /** 上次 Huly 连接尝试时间（ISO 8601） */
  readonly last_connect_attempt: string | null
  /** 最近一次连接错误（若 huly_connected=false） */
  readonly last_error: string | null
}

// ============================================================================
// Plan 05 — 业务路由请求 / 响应 schema
// ============================================================================

/**
 * POST /api/im/send_dm 请求体。
 *
 * Python backend HulyIMProvider.send_dm 调用。
 */
export interface SendDmRequest {
  /** 目标 username（Plan 06 seed 后形如 "hr.alice" / "zhang.san"） */
  readonly to_username: string
  /** Markdown 文本（中文可，长度 ≤ Huly chunter ChatMessage 限制） */
  readonly markdown: string
}

/**
 * POST /api/im/post_channel 请求体。
 */
export interface PostChannelRequest {
  /** 目标 Channel id（已知的 chunter.class.Channel _id） */
  readonly channel_id: string
  /** Markdown 文本 */
  readonly markdown: string
}

/**
 * POST /api/im/ensure_member 请求体。
 */
export interface EnsureMemberRequest {
  /** 目标 Channel id */
  readonly channel_id: string
  /** 要加进 channel 的 username */
  readonly username: string
}

/**
 * IM 路由通用成功响应 data 字段。
 */
export interface ImSendDmResult {
  readonly message_id: string
  readonly dm_id: string
}

export interface ImPostChannelResult {
  readonly message_id: string
}

export interface ImEnsureMemberResult {
  readonly already_member: boolean
}

// ============================================================================
// Doc 路由
// ============================================================================

/**
 * POST /api/doc/create_space 请求体。
 *
 * 对应 Python HulyDocProvider.create_collection — 创建 Teamspace。
 */
export interface CreateSpaceRequest {
  /** Space 显示名（如 "离职 · zhang.san"） */
  readonly name: string
  /** Space 所属 owner（owner_username → AccountUuid） */
  readonly owner_username: string
}

export interface CreateSpaceResult {
  readonly space_id: string
}

/**
 * POST /api/doc/create_doc 请求体。
 */
export interface CreateDocRequest {
  readonly space_id: string
  readonly title: string
  readonly markdown: string
  /** 可选父文档 id；空 → 创建为根级 doc */
  readonly parent_id?: string
}

export interface CreateDocResult {
  readonly doc_id: string
  /** 完整 web URL */
  readonly url: string
  readonly title: string
}

export interface ListInSpaceResult {
  readonly docs: ReadonlyArray<{
    readonly id: string
    readonly title: string
    readonly url: string
  }>
}

// ============================================================================
// Plan 06 — Admin 路由请求 / 响应 schema
// ============================================================================

/**
 * POST /api/admin/signup_join 请求体。
 *
 * Plan 06 seed_huly_users.py 调用，把业务 DB user 同步到 Huly account + workspace。
 */
export interface SignUpJoinRequest {
  /** 业务侧 username（"hr.alice" / "zhang.san"），仅用于 log / 错误信息 */
  readonly username: string
  /** Huly 账号 email（约定为 `{username}@demo.local`） */
  readonly email: string
  /** Huly 账号密码（仅 seed 用；演示场景统一用 HULY_DEFAULT_PASSWORD） */
  readonly password: string
  /** Huly 账号 first name（用于 UI 显示） */
  readonly first_name: string
  /** Huly 账号 last name */
  readonly last_name: string
  /** Workspace role，缺省 'USER' */
  readonly role?: string
}

/**
 * POST /api/admin/signup_join 响应 data 字段。
 */
export interface SignUpJoinResult {
  /** 新建 / 已存在的 account UUID */
  readonly account_uuid: string
  /** true = 账号已存在，本次未创建；false = 本次新建 */
  readonly skipped: boolean
}

/**
 * Plan 05 — 反向 webhook payload（sidecar → backend）。
 *
 * sidecar listener.ts 检测到 chat 消息时 POST 这个 body 到
 * `${BACKEND_URL}/api/internal/huly/event`（X-Bridge-Token 鉴权）。
 */
export interface ChatEventPayload {
  /** Huly 平台 modifiedBy = AccountUuid */
  readonly sender_account: string
  /** 反查得到的业务 username（"hr.alice"），失败时为 undefined */
  readonly sender_username?: string
  /** 消息所在 channel id（dm._id / channel._id） */
  readonly channel_id: string
  /** Huly 端 attachedToClass — 用于映射 channel_type */
  readonly attached_to_class: string
  /** Markdown 消息文本 */
  readonly message: string
  /** Huly 端创建时间（ms epoch） */
  readonly ts: number
}
