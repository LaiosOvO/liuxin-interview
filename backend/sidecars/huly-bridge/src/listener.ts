/**
 * huly-bridge sidecar — 反向 chat 订阅（Huly → backend webhook）
 *
 * Phase 8 / HULY-05
 *
 * 实现机制（v1）：
 * - 2s 轮询 `client.findAll(chunter.class.ChatMessage, { createdOn: { $gt: lastSeen } })`
 * - 发现新消息 → POST 到 ${BACKEND_URL}/api/internal/huly/event（X-Bridge-Token 鉴权）
 * - 死循环防护：跳过 modifiedBy === botAccountUuid 的消息（Pitfall #6）
 *
 * v2 升级路径（暂不实现）：换 Huly live subscription（client.subscribe）— 见 RESEARCH §Open Questions #2
 *
 * 设计约束：
 * - setInterval 不能引入 unhandled rejection（每次 tick 内 try/catch）
 * - fetch 失败仅 log + 不影响后续 poll 循环
 * - lastSeen 单调递增（Math.max 防止时间倒退）
 * - 返回 interval handle 供 index.ts 优雅关停（SIGTERM 收时 clearInterval）
 */

import chunterModule from '@hcengineering/chunter'
import contactModule from '@hcengineering/contact'

import type { PlatformClient } from '@hcengineering/api-client'

import type { BridgeConfig, ChatEventPayload } from './types.js'

const POLL_INTERVAL_MS = 2000

/**
 * CJS lookup helper（与 im.ts / doc.ts 同模式）。
 */
function lookup<T>(mod: unknown, path: readonly string[]): T | undefined {
  let cur: unknown = mod
  for (const key of path) {
    if (cur === undefined || cur === null) return undefined
    cur = (cur as Record<string, unknown>)[key]
  }
  return cur as T
}

function getChunterChatMessageClass(): unknown {
  return (
    lookup(chunterModule, ['class', 'ChatMessage']) ??
    lookup(chunterModule, ['default', 'class', 'ChatMessage'])
  )
}

function getContactSocialIdentityClass(): unknown {
  return (
    lookup(contactModule, ['class', 'SocialIdentity']) ??
    lookup(contactModule, ['default', 'class', 'SocialIdentity'])
  )
}

function getContactEmployeeMixin(): unknown {
  return (
    lookup(contactModule, ['mixin', 'Employee']) ??
    lookup(contactModule, ['default', 'mixin', 'Employee'])
  )
}

/**
 * 反查 sender_username（personUuid → SocialIdentity.key → split '@'）。
 *
 * 失败返回 undefined（backend 端可继续处理 sender_account UUID）。
 *
 * @param client PlatformClient
 * @param accountUuid 消息的 modifiedBy（personUuid）
 */
export async function reverseLookupUsername(
  client: PlatformClient,
  accountUuid: string,
): Promise<string | undefined> {
  try {
    const employeeMixin = getContactEmployeeMixin()
    const socialIdClass = getContactSocialIdentityClass()
    if (employeeMixin === undefined || socialIdClass === undefined) return undefined

    // accountUuid → Employee（找 personUuid 字段匹配）
    const employee = (await client.findOne(employeeMixin, { personUuid: accountUuid })) as
      | { _id: string }
      | undefined
    if (employee === undefined || employee === null) return undefined

    // Employee._id → SocialIdentity by attachedTo
    const socialId = (await client.findOne(socialIdClass, { attachedTo: employee._id })) as
      | { key?: string }
      | undefined
    if (socialId === undefined || socialId === null || !socialId.key) return undefined

    // key = 'email:hr.alice@demo.local' → 拿 'hr.alice'
    const emailPart = socialId.key.replace(/^email:/, '')
    const username = emailPart.split('@')[0]
    return username || undefined
  } catch (err) {
    console.warn('[huly-bridge:listener] reverseLookupUsername 失败:', err)
    return undefined
  }
}

/**
 * 把 Huly 的 attachedToClass 映射成业务侧 channel_type（'D' / 'O' / 'P'）。
 *
 * 沿用 MM 约定（dispatcher 内 channel_type='D' 触发 DM 逻辑）。
 */
export function mapChannelType(attachedToClass: string): 'D' | 'O' | 'P' {
  // chunter:class:DirectMessage 形如 "chunter:class:DirectMessage"
  const lower = attachedToClass.toLowerCase()
  if (lower.includes('directmessage')) return 'D'
  // chunter:class:Channel 与可能的 PrivateChannel
  if (lower.includes('privatechannel') || lower.endsWith(':privatechannel')) return 'P'
  return 'O'
}

/**
 * 处理单条 chat 消息：跳自己 + 反查 username + POST backend webhook。
 *
 * 抽出来供单测使用（测试 fetch 调用）。
 *
 * @param client PlatformClient
 * @param msg Huly chunter.ChatMessage doc
 * @param config BridgeConfig（用 backendUrl / bridgeToken）
 * @param botAccountUuid 防死循环
 */
export async function processOneMessage(
  client: PlatformClient,
  msg: {
    _id: string
    modifiedBy: string
    attachedTo: string
    attachedToClass: string
    message: string
    createdOn: number
  },
  config: BridgeConfig,
  botAccountUuid: string,
): Promise<boolean> {
  // 跳自己（Pitfall #6 死循环防护）
  if (msg.modifiedBy === botAccountUuid) {
    return false
  }

  const senderUsername = await reverseLookupUsername(client, msg.modifiedBy)
  const channelType = mapChannelType(msg.attachedToClass)

  const payload: ChatEventPayload = {
    sender_account: msg.modifiedBy,
    sender_username: senderUsername,
    channel_id: msg.attachedTo,
    attached_to_class: msg.attachedToClass,
    message: msg.message,
    ts: msg.createdOn,
  }

  try {
    const response = await fetch(`${config.backendUrl}/api/internal/huly/event`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Bridge-Token': config.bridgeToken,
      },
      body: JSON.stringify({ ...payload, channel_type: channelType }),
    })
    if (!response.ok) {
      console.warn(
        `[huly-bridge:listener] backend webhook 返回非 2xx: ${response.status} (msg=${msg._id})`,
      )
      return false
    }
    return true
  } catch (err) {
    // 网络/超时仅 log，不抛
    console.warn('[huly-bridge:listener] backend webhook 调用失败:', err)
    return false
  }
}

/**
 * 启动 chat poll listener — 返回 interval handle 用于 SIGTERM 优雅关停。
 *
 * @param client PlatformClient
 * @param config BridgeConfig
 * @param botAccountUuid 死循环防护标识
 */
export async function startChatListener(
  client: PlatformClient,
  config: BridgeConfig,
  botAccountUuid: string,
): Promise<NodeJS.Timeout> {
  let lastSeen = Date.now()
  const chatMessageClass = getChunterChatMessageClass()
  if (chatMessageClass === undefined) {
    throw new Error('huly-bridge: chunter.class.ChatMessage 未导出 — 检查 SDK 版本')
  }

  console.log(
    `[huly-bridge:listener] 启动 chat 轮询（间隔 ${POLL_INTERVAL_MS}ms / 死循环防护 botAccount=${botAccountUuid.slice(0, 8)}...）`,
  )

  const handle = setInterval((): void => {
    void (async (): Promise<void> => {
      try {
        const msgs = (await client.findAll(
          chatMessageClass,
          { createdOn: { $gt: lastSeen } },
          { sort: { createdOn: 1 }, limit: 100 },
        )) as Array<{
          _id: string
          modifiedBy: string
          attachedTo: string
          attachedToClass: string
          message: string
          createdOn: number
        }>

        for (const msg of msgs) {
          lastSeen = Math.max(lastSeen, msg.createdOn)
          await processOneMessage(client, msg, config, botAccountUuid)
        }
      } catch (err) {
        // 任何错误（如 Huly 临时不可达）只 log，不让 interval 中断
        console.warn('[huly-bridge:listener] poll tick 错误（继续下一轮）:', err)
      }
    })()
  }, POLL_INTERVAL_MS)

  // unref() 让进程退出时不被这个定时器卡住
  handle.unref()

  return handle
}
