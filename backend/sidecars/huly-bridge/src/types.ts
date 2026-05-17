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
