/**
 * huly-bridge sidecar — Huly service token 生成
 *
 * Phase 8 / HULY-04 — service token 模式（已源码验证）
 *
 * 设计参考（RESEARCH §3.3.1，逐文件源码验证）：
 * - hcengineering/platform:services/telegram-bot/pod-telegram-bot/src/utils.ts (serviceToken)
 * - hcengineering/platform:services/telegram-bot/pod-telegram-bot/src/start.ts (setMetadata)
 * - hcengineering/platform:foundations/core/packages/token/src/token.ts (generateToken 签名)
 *
 * 用法：
 *   initAuth(config)           // sidecar 启动时调用一次（setMetadata）
 *   const token = serviceToken() // 每次需要 Huly token 时调用（generateToken）
 */

import { systemAccountUuid } from '@hcengineering/core'
import { setMetadata } from '@hcengineering/platform'
import serverClient from '@hcengineering/server-client'
import serverToken, { generateToken } from '@hcengineering/server-token'

import type { BridgeConfig } from './types.js'

/**
 * 内部状态：是否已调过 initAuth。
 *
 * generateToken 依赖 setMetadata(serverToken.metadata.Secret, ...) 已 set；
 * 未 set 时 generateToken 会抛错。本 flag 用于早期检测。
 */
let initialized = false

/**
 * 当前进程使用的 service name（在 initAuth 时记下，serviceToken 时塞进 extra）。
 *
 * Huly v0.7 token extra.service 是 service-to-service 鉴权的关键字段：
 * - Huly transactor 会在某些 API 校验 service 名（如 createInviteLink 限制 service='schedule'）
 * - 我们用 'offboarding-bot' 作为审计可追溯的服务标识
 */
let currentServiceName: string | null = null

/**
 * 初始化鉴权 — 设置 Huly SDK 全局 metadata。
 *
 * 必须在 generateToken / connect 之前调用一次。重复调用会更新 metadata
 * （Huly SDK 的 setMetadata 是覆盖语义）。
 *
 * @param config 已加载的 BridgeConfig
 */
export function initAuth(config: BridgeConfig): void {
  // 步骤 1：设置 HMAC secret（generateToken 用它签 JWT）
  setMetadata(serverToken.metadata.Secret, config.serverSecret)

  // 步骤 2：设置 service name（generateToken 写到 token extra.service）
  setMetadata(serverToken.metadata.Service, config.serviceName)

  // 步骤 3：设置 server-client endpoint（Huly accounts API）
  // 后续 connect()/getAccountClient() 会读这个 metadata
  setMetadata(serverClient.metadata.Endpoint, config.hulyAccountsUrl)
  setMetadata(serverClient.metadata.UserAgent, `${config.serviceName}/0.1.0`)

  currentServiceName = config.serviceName
  initialized = true
}

/**
 * 生成 Huly service token（不绑定 workspace）。
 *
 * 模式（已源码验证 — RESEARCH §3.3.1）：
 *   generateToken(systemAccountUuid, undefined, { service: 'offboarding-bot' })
 *
 * 参数语义：
 * - accountUuid = systemAccountUuid：系统账号（拥有全 workspace 访问权）
 * - workspaceUuid = undefined：service token 不绑特定 workspace（connect 时按需指定）
 * - extra = { service }：审计标识；某些 Huly API 会校验
 *
 * @returns 签好的 JWT 字符串（直接给 connect / accountClient 用）
 * @throws Error 若 initAuth 未先调用
 */
export function serviceToken(): string {
  if (!initialized || currentServiceName === null) {
    throw new Error('huly-bridge: serviceToken() 调用前必须先 initAuth() — Huly SDK metadata 未设置')
  }

  // generateToken 第二参数 workspaceUuid 用 undefined 表示「不绑 workspace」
  // 第三参数 extra 必须含 service 字段（Huly v0.7 token schema 要求）
  return generateToken(systemAccountUuid, undefined, {
    service: currentServiceName,
  })
}

/**
 * 测试用 — 重置 initialized flag（避免测试相互污染）。
 *
 * 注意：Huly SDK 的 setMetadata 没有「清除」API，所以本函数只重置我们的内部 flag。
 * 真实重置 metadata 需要重新 setMetadata 覆盖。
 *
 * @internal 仅 tests 使用
 */
export function _resetAuthForTests(): void {
  initialized = false
  currentServiceName = null
}

/**
 * 测试用 — 查询当前是否已 init。
 *
 * @internal 仅 tests 使用
 */
export function _isAuthInitialized(): boolean {
  return initialized
}
