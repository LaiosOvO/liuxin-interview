/**
 * huly-bridge sidecar — IM 业务路由
 *
 * Phase 8 / HULY-05
 *
 * 提供 3 个 HTTP 路由：
 * - POST /api/im/send_dm     — 私聊（自动建/复用 DirectMessage space）
 * - POST /api/im/post_channel — 发到指定 Channel
 * - POST /api/im/ensure_member — 把 user 加进 Channel（成员幂等）
 *
 * 设计要点（参考 ~/ai/ref/agent/huly/services/ai-bot/pod-ai-bot/src/utils/platform.ts）：
 * - 用户身份解析：socialKey: `email:{username}@demo.local` → SocialIdentity →
 *   Employee mixin → personUuid (= AccountUuid)
 * - DM 查/建模式：findAll DirectMessage by members → match botAccount+targetAccount →
 *   缺则 createDoc 新 DM 到 core.space.Space
 * - 消息发送模式：addCollection chunter.class.ChatMessage 到 dm._id / channel._id
 *
 * 错误处理：所有 endpoint try/catch；
 * - 用户不存在 → 404 (USER_NOT_FOUND)
 * - 其他错误 → 500 (INTERNAL_ERROR)，详细 stack 仅 log 不暴露给 caller
 */

import chunterModule from '@hcengineering/chunter'
import contactModule from '@hcengineering/contact'
import coreModule from '@hcengineering/core'
import type { Express, Request, Response } from 'express'

import type { PlatformClient } from '@hcengineering/api-client'

import type {
  EnsureMemberRequest,
  ErrorResponse,
  ImEnsureMemberResult,
  ImPostChannelResult,
  ImSendDmResult,
  PostChannelRequest,
  SendDmRequest,
  SuccessResponse,
} from './types.js'

/**
 * Plan 06 seed 期间所有 demo 用户的 email 域名（PRD §16）。
 * SocialIdentity.key = `email:{username}@demo.local`
 */
const DEMO_EMAIL_DOMAIN = 'demo.local'

/**
 * CJS interop — 从 default export / 顶级 lookup 一个属性。
 * 与 src/auth.ts / src/index.ts 相同模式（@hcengineering/* 是 esbuild CJS 输出）。
 */
function lookup<T>(mod: unknown, path: readonly string[]): T | undefined {
  let cur: unknown = mod
  for (const key of path) {
    if (cur === undefined || cur === null) return undefined
    cur = (cur as Record<string, unknown>)[key]
  }
  return cur as T
}

function getChunterClass(name: 'DirectMessage' | 'Channel' | 'ChatMessage'): unknown {
  return (
    lookup(chunterModule, ['class', name]) ??
    lookup(chunterModule, ['default', 'class', name])
  )
}

function getContactClass(name: 'SocialIdentity'): unknown {
  return (
    lookup(contactModule, ['class', name]) ??
    lookup(contactModule, ['default', 'class', name])
  )
}

function getContactMixin(name: 'Employee'): unknown {
  return (
    lookup(contactModule, ['mixin', name]) ??
    lookup(contactModule, ['default', 'mixin', name])
  )
}

function getCoreSpaceSpace(): unknown {
  return (
    lookup(coreModule, ['space', 'Space']) ??
    lookup(coreModule, ['default', 'space', 'Space'])
  )
}

/**
 * 生成唯一文档 id —— Huly v0.7 用 ObjectId-like 字符串。
 *
 * 由于 @hcengineering/core 的 generateId 在 ESM/CJS interop 下可能 lookup 不到，
 * 这里用本地实现作为安全 fallback（时间戳 + 随机后缀，64 位足够避碰撞）。
 */
function generateId(): string {
  const fn = lookup<() => string>(coreModule, ['generateId']) ??
    lookup<() => string>(coreModule, ['default', 'generateId'])
  if (typeof fn === 'function') return fn()
  // Fallback — 26 字符 base36 时间戳 + 12 字符随机
  return (
    Date.now().toString(36) +
    '-' +
    Math.random().toString(36).slice(2, 14)
  )
}

/**
 * 通过 username 解出 Huly AccountUuid（personUuid）。
 *
 * 流程（参考 ai-bot/utils/platform.ts:getAccountBySocialKey）：
 * 1. SocialIdentity by key 'email:{username}@demo.local' → 拿 attachedTo (PersonId)
 * 2. Employee mixin by _id=PersonId → 拿 personUuid
 * 3. 找不到任何一步返回 null（路由层 404）
 *
 * @param client PlatformClient
 * @param username 业务侧 username（"hr.alice" / "zhang.san"）
 * @returns AccountUuid 字符串 / null
 */
export async function resolveAccountByUsername(
  client: PlatformClient,
  username: string,
): Promise<string | null> {
  if (!username || typeof username !== 'string') return null

  const socialIdentityClass = getContactClass('SocialIdentity')
  const employeeMixin = getContactMixin('Employee')
  if (socialIdentityClass === undefined || employeeMixin === undefined) {
    throw new Error('huly-bridge: @hcengineering/contact 未导出 SocialIdentity / Employee mixin')
  }

  const socialKey = `email:${username}@${DEMO_EMAIL_DOMAIN}`
  const socialId = (await client.findOne(socialIdentityClass, { key: socialKey })) as
    | { attachedTo?: string }
    | undefined
  if (socialId === undefined || socialId === null || !socialId.attachedTo) {
    return null
  }

  const employee = (await client.findOne(employeeMixin, { _id: socialId.attachedTo })) as
    | { personUuid?: string }
    | undefined
  return employee?.personUuid ?? null
}

/**
 * 查/建 DirectMessage space（bot 与 target 双向 1-to-1）。
 *
 * 复用模式（ai-bot/utils/platform.ts:getDirect）：
 * - findAll(DirectMessage, {members: botAccount}) → 过滤 members 集合恰为 {bot, target}
 * - 找到 → 复用 _id
 * - 没找到 → createDoc 新 DM 到 core.space.Space，members=[bot, target]
 *
 * @param client PlatformClient
 * @param botAccount bot 的 AccountUuid
 * @param targetAccount target 用户的 AccountUuid
 * @returns dmId 字符串
 */
export async function ensureDirectMessage(
  client: PlatformClient,
  botAccount: string,
  targetAccount: string,
): Promise<string> {
  const dmClass = getChunterClass('DirectMessage')
  const coreSpace = getCoreSpaceSpace()
  if (dmClass === undefined || coreSpace === undefined) {
    throw new Error('huly-bridge: @hcengineering/chunter.class.DirectMessage 或 core.space.Space 未导出')
  }

  const existingDms = (await client.findAll(dmClass, { members: botAccount })) as Array<{
    _id: string
    members: string[]
  }>

  const match = existingDms.find(
    (dm) =>
      Array.isArray(dm.members) &&
      dm.members.length === 2 &&
      dm.members.includes(botAccount) &&
      dm.members.includes(targetAccount),
  )

  if (match !== undefined) {
    return match._id
  }

  const dmId = await client.createDoc(dmClass, coreSpace, {
    name: '',
    description: '',
    private: true,
    archived: false,
    members: [botAccount, targetAccount],
  })

  return dmId
}

/**
 * 在指定 space (DM / Channel) 内附加一条 ChatMessage。
 *
 * @param client PlatformClient
 * @param parentSpaceId 父 space 的 _id（dmId / channelId）
 * @param parentClass 父 class（chunter.class.DirectMessage / chunter.class.Channel）
 * @param markdown 消息文本
 * @returns 新建的 ChatMessage _id
 */
export async function addChatMessage(
  client: PlatformClient,
  parentSpaceId: string,
  parentClass: unknown,
  markdown: string,
): Promise<string> {
  const chatMessageClass = getChunterClass('ChatMessage')
  if (chatMessageClass === undefined) {
    throw new Error('huly-bridge: @hcengineering/chunter.class.ChatMessage 未导出')
  }
  const messageId = generateId()
  await client.addCollection(
    chatMessageClass,
    parentSpaceId,
    parentSpaceId,
    parentClass,
    'messages',
    { message: markdown, attachments: 0 },
    messageId,
  )
  return messageId
}

/**
 * 提取 ErrorResponse helper — 路由错误统一格式。
 */
function errorBody(error: string, code: string): ErrorResponse {
  return { ok: false, error, code }
}

/**
 * 验证 send_dm 请求体（避免 Express body parser 后的 undefined 字段）。
 */
function validateSendDm(body: unknown): SendDmRequest | string {
  if (typeof body !== 'object' || body === null) return '请求体必须是 JSON 对象'
  const b = body as Partial<SendDmRequest>
  if (typeof b.to_username !== 'string' || b.to_username.trim() === '') {
    return '缺少 to_username 字段'
  }
  if (typeof b.markdown !== 'string' || b.markdown === '') {
    return '缺少 markdown 字段'
  }
  return { to_username: b.to_username.trim(), markdown: b.markdown }
}

function validatePostChannel(body: unknown): PostChannelRequest | string {
  if (typeof body !== 'object' || body === null) return '请求体必须是 JSON 对象'
  const b = body as Partial<PostChannelRequest>
  if (typeof b.channel_id !== 'string' || b.channel_id.trim() === '') {
    return '缺少 channel_id 字段'
  }
  if (typeof b.markdown !== 'string' || b.markdown === '') {
    return '缺少 markdown 字段'
  }
  return { channel_id: b.channel_id.trim(), markdown: b.markdown }
}

function validateEnsureMember(body: unknown): EnsureMemberRequest | string {
  if (typeof body !== 'object' || body === null) return '请求体必须是 JSON 对象'
  const b = body as Partial<EnsureMemberRequest>
  if (typeof b.channel_id !== 'string' || b.channel_id.trim() === '') {
    return '缺少 channel_id 字段'
  }
  if (typeof b.username !== 'string' || b.username.trim() === '') {
    return '缺少 username 字段'
  }
  return { channel_id: b.channel_id.trim(), username: b.username.trim() }
}

/**
 * 在 Express app 上挂 IM 业务路由。
 *
 * @param app Express 实例
 * @param client 已 connect 的 PlatformClient（Plan 04 提供）
 * @param botAccount bot 的 AccountUuid（来自 systemAccountUuid 或 Plan 06 seed 后真实 bot 账号）
 */
export function mountImRoutes(app: Express, client: PlatformClient, botAccount: string): void {
  // ============================================================================
  // POST /api/im/send_dm
  // ============================================================================
  app.post('/api/im/send_dm', async (req: Request, res: Response): Promise<void> => {
    const validated = validateSendDm(req.body)
    if (typeof validated === 'string') {
      res.status(400).json(errorBody(validated, 'BAD_REQUEST'))
      return
    }
    const { to_username, markdown } = validated

    try {
      const targetAccount = await resolveAccountByUsername(client, to_username)
      if (targetAccount === null) {
        res
          .status(404)
          .json(errorBody(`未找到 username=${to_username} 对应的 Huly account`, 'USER_NOT_FOUND'))
        return
      }

      const dmId = await ensureDirectMessage(client, botAccount, targetAccount)
      const dmClass = getChunterClass('DirectMessage')
      const messageId = await addChatMessage(client, dmId, dmClass, markdown)

      const data: ImSendDmResult = { message_id: messageId, dm_id: dmId }
      const body: SuccessResponse<ImSendDmResult> = { ok: true, data }
      res.status(200).json(body)
    } catch (err) {
      console.error('[huly-bridge:im] send_dm 失败:', err)
      const message = err instanceof Error ? err.message : 'send_dm 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })

  // ============================================================================
  // POST /api/im/post_channel
  // ============================================================================
  app.post('/api/im/post_channel', async (req: Request, res: Response): Promise<void> => {
    const validated = validatePostChannel(req.body)
    if (typeof validated === 'string') {
      res.status(400).json(errorBody(validated, 'BAD_REQUEST'))
      return
    }
    const { channel_id, markdown } = validated

    try {
      const channelClass = getChunterClass('Channel')
      if (channelClass === undefined) {
        throw new Error('chunter.class.Channel 未导出')
      }
      const messageId = await addChatMessage(client, channel_id, channelClass, markdown)
      const data: ImPostChannelResult = { message_id: messageId }
      const body: SuccessResponse<ImPostChannelResult> = { ok: true, data }
      res.status(200).json(body)
    } catch (err) {
      console.error('[huly-bridge:im] post_channel 失败:', err)
      const message = err instanceof Error ? err.message : 'post_channel 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })

  // ============================================================================
  // POST /api/im/ensure_member
  // ============================================================================
  app.post('/api/im/ensure_member', async (req: Request, res: Response): Promise<void> => {
    const validated = validateEnsureMember(req.body)
    if (typeof validated === 'string') {
      res.status(400).json(errorBody(validated, 'BAD_REQUEST'))
      return
    }
    const { channel_id, username } = validated

    try {
      const targetAccount = await resolveAccountByUsername(client, username)
      if (targetAccount === null) {
        res
          .status(404)
          .json(errorBody(`未找到 username=${username} 对应的 Huly account`, 'USER_NOT_FOUND'))
        return
      }

      const channelClass = getChunterClass('Channel')
      if (channelClass === undefined) {
        throw new Error('chunter.class.Channel 未导出')
      }
      const channel = (await client.findOne(channelClass, { _id: channel_id })) as
        | { _id: string; members?: string[] }
        | undefined
      if (channel === undefined || channel === null) {
        res
          .status(404)
          .json(errorBody(`未找到 channel_id=${channel_id} 对应的 Huly Channel`, 'CHANNEL_NOT_FOUND'))
        return
      }

      const currentMembers = Array.isArray(channel.members) ? channel.members : []
      if (currentMembers.includes(targetAccount)) {
        const data: ImEnsureMemberResult = { already_member: true }
        res.status(200).json({ ok: true, data } satisfies SuccessResponse<ImEnsureMemberResult>)
        return
      }

      await client.updateDoc(channelClass, channel_id, channel, {
        $push: { members: targetAccount },
      })

      const data: ImEnsureMemberResult = { already_member: false }
      res.status(200).json({ ok: true, data } satisfies SuccessResponse<ImEnsureMemberResult>)
    } catch (err) {
      console.error('[huly-bridge:im] ensure_member 失败:', err)
      const message = err instanceof Error ? err.message : 'ensure_member 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })
}

export { generateId as _testGenerateId, getChunterClass as _testGetChunterClass }
