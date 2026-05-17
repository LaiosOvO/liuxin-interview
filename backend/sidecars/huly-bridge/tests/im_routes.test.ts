/**
 * huly-bridge sidecar — im.ts 业务路由测试
 *
 * Phase 8 / HULY-05
 *
 * 覆盖：
 * - send_dm: 用户不存在 → 404
 * - send_dm: DM 已存在 → 复用 dmId + addCollection 调用
 * - send_dm: DM 不存在 → createDoc + addCollection 双调用
 * - post_channel: addCollection on Channel 调用
 * - ensure_member: 已在成员 → no-op
 * - ensure_member: 不在成员 → updateDoc $push
 */

import express, { type Express } from 'express'
import supertest from 'supertest'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock @hcengineering/* — 复用 healthz.test.ts 模式，default + 顶级双挂
const mockChunterClass = {
  DirectMessage: Symbol('chunter.class.DirectMessage'),
  Channel: Symbol('chunter.class.Channel'),
  ChatMessage: Symbol('chunter.class.ChatMessage'),
}

const mockContactClass = {
  SocialIdentity: Symbol('contact.class.SocialIdentity'),
  Person: Symbol('contact.class.Person'),
}

const mockContactMixin = {
  Employee: Symbol('contact.mixin.Employee'),
}

const mockCoreSpace = {
  Space: Symbol('core.space.Space'),
}

vi.mock('@hcengineering/chunter', () => ({
  default: { class: mockChunterClass },
  class: mockChunterClass,
}))

vi.mock('@hcengineering/contact', () => ({
  default: { class: mockContactClass, mixin: mockContactMixin },
  class: mockContactClass,
  mixin: mockContactMixin,
}))

vi.mock('@hcengineering/core', () => ({
  default: {
    space: mockCoreSpace,
    generateId: () => 'mock-generated-id',
  },
  space: mockCoreSpace,
  generateId: () => 'mock-generated-id',
  systemAccountUuid: '00000000-0000-0000-0000-000000000001',
}))

// Lazy import — 确保 vi.mock 在 import 之前生效
let mountImRoutes: typeof import('../src/im.js').mountImRoutes
let resolveAccountByUsername: typeof import('../src/im.js').resolveAccountByUsername
let ensureDirectMessage: typeof import('../src/im.js').ensureDirectMessage

beforeAll(async () => {
  const im = await import('../src/im.js')
  mountImRoutes = im.mountImRoutes
  resolveAccountByUsername = im.resolveAccountByUsername
  ensureDirectMessage = im.ensureDirectMessage
})

/**
 * 构造一个 mock PlatformClient — 测试用 stub。
 *
 * 用 vi.fn() 让每个测试独立控制返回值 + 校验调用次数。
 */
interface MockPlatformClient {
  findOne: ReturnType<typeof vi.fn>
  findAll: ReturnType<typeof vi.fn>
  createDoc: ReturnType<typeof vi.fn>
  updateDoc: ReturnType<typeof vi.fn>
  addCollection: ReturnType<typeof vi.fn>
  removeDoc: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

function makeMockClient(): MockPlatformClient {
  return {
    findOne: vi.fn(),
    findAll: vi.fn(),
    createDoc: vi.fn(),
    updateDoc: vi.fn(),
    addCollection: vi.fn(),
    removeDoc: vi.fn(),
    close: vi.fn(),
  }
}

const BOT_ACCOUNT = 'bot-account-uuid-0001'

/**
 * 创建 Express app + mount IM 路由（不带 bridgeAuth — 测试聚焦业务逻辑）。
 */
function makeApp(client: MockPlatformClient): Express {
  const app = express()
  app.use(express.json())
  mountImRoutes(app, client as unknown as Parameters<typeof mountImRoutes>[1], BOT_ACCOUNT)
  return app
}

describe('resolveAccountByUsername', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('找不到 SocialIdentity → 返回 null', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce(undefined)

    const result = await resolveAccountByUsername(
      client as unknown as Parameters<typeof resolveAccountByUsername>[0],
      'hr.alice',
    )

    expect(result).toBeNull()
    expect(client.findOne).toHaveBeenCalledWith(
      mockContactClass.SocialIdentity,
      { key: 'email:hr.alice@demo.local' },
    )
  })

  it('SocialIdentity 找到但 Employee 缺 → null', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-id-1' })
      .mockResolvedValueOnce(undefined)

    const result = await resolveAccountByUsername(
      client as unknown as Parameters<typeof resolveAccountByUsername>[0],
      'hr.alice',
    )

    expect(result).toBeNull()
  })

  it('SocialIdentity + Employee 都找到 → 返回 personUuid', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-id-1' })
      .mockResolvedValueOnce({ personUuid: 'account-uuid-alice' })

    const result = await resolveAccountByUsername(
      client as unknown as Parameters<typeof resolveAccountByUsername>[0],
      'hr.alice',
    )

    expect(result).toBe('account-uuid-alice')
  })
})

describe('ensureDirectMessage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('已有 DM 含 bot+target → 返回现有 dmId（不调 createDoc）', async () => {
    const client = makeMockClient()
    client.findAll.mockResolvedValueOnce([
      {
        _id: 'dm-existing-1',
        members: [BOT_ACCOUNT, 'account-uuid-alice'],
      },
    ])

    const dmId = await ensureDirectMessage(
      client as unknown as Parameters<typeof ensureDirectMessage>[0],
      BOT_ACCOUNT,
      'account-uuid-alice',
    )

    expect(dmId).toBe('dm-existing-1')
    expect(client.createDoc).not.toHaveBeenCalled()
  })

  it('没有匹配 DM → createDoc 新 DM 到 core.space.Space + members=[bot,target]', async () => {
    const client = makeMockClient()
    client.findAll.mockResolvedValueOnce([])
    client.createDoc.mockResolvedValueOnce('dm-new-1')

    const dmId = await ensureDirectMessage(
      client as unknown as Parameters<typeof ensureDirectMessage>[0],
      BOT_ACCOUNT,
      'account-uuid-alice',
    )

    expect(dmId).toBe('dm-new-1')
    expect(client.createDoc).toHaveBeenCalledWith(
      mockChunterClass.DirectMessage,
      mockCoreSpace.Space,
      expect.objectContaining({
        name: '',
        private: true,
        archived: false,
        members: [BOT_ACCOUNT, 'account-uuid-alice'],
      }),
    )
  })
})

describe('POST /api/im/send_dm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('用户不存在 → 404 USER_NOT_FOUND', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/send_dm')
      .send({ to_username: 'unknown', markdown: 'hi' })

    expect(res.status).toBe(404)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'USER_NOT_FOUND',
    })
    expect(client.createDoc).not.toHaveBeenCalled()
    expect(client.addCollection).not.toHaveBeenCalled()
  })

  it('DM 已存在 → 复用 dmId + addCollection 被调用一次', async () => {
    const client = makeMockClient()
    // resolveAccountByUsername: 2 次 findOne
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-id-1' })
      .mockResolvedValueOnce({ personUuid: 'account-uuid-alice' })
    // ensureDirectMessage: 1 次 findAll
    client.findAll.mockResolvedValueOnce([
      { _id: 'dm-existing-1', members: [BOT_ACCOUNT, 'account-uuid-alice'] },
    ])

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/send_dm')
      .send({ to_username: 'hr.alice', markdown: 'hello world' })

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({
      ok: true,
      data: { dm_id: 'dm-existing-1' },
    })
    expect(client.createDoc).not.toHaveBeenCalled() // 复用现有 DM
    expect(client.addCollection).toHaveBeenCalledTimes(1)
    expect(client.addCollection).toHaveBeenCalledWith(
      mockChunterClass.ChatMessage,
      'dm-existing-1',
      'dm-existing-1',
      mockChunterClass.DirectMessage,
      'messages',
      expect.objectContaining({ message: 'hello world', attachments: 0 }),
      expect.any(String),
    )
  })

  it('DM 不存在 → createDoc 新 DM + addCollection 被调用', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-id-2' })
      .mockResolvedValueOnce({ personUuid: 'account-uuid-bob' })
    client.findAll.mockResolvedValueOnce([])
    client.createDoc.mockResolvedValueOnce('dm-new-bob')

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/send_dm')
      .send({ to_username: 'zhang.san', markdown: '你好' })

    expect(res.status).toBe(200)
    expect(res.body.data.dm_id).toBe('dm-new-bob')
    expect(client.createDoc).toHaveBeenCalledTimes(1)
    expect(client.addCollection).toHaveBeenCalledTimes(1)
  })

  it('请求体缺 markdown → 400 BAD_REQUEST', async () => {
    const client = makeMockClient()
    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/send_dm')
      .send({ to_username: 'hr.alice' })

    expect(res.status).toBe(400)
    expect(res.body.code).toBe('BAD_REQUEST')
  })
})

describe('POST /api/im/post_channel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('addCollection on Channel 被调用一次', async () => {
    const client = makeMockClient()

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/post_channel')
      .send({ channel_id: 'channel-1', markdown: 'announcement' })

    expect(res.status).toBe(200)
    expect(res.body.ok).toBe(true)
    expect(client.addCollection).toHaveBeenCalledTimes(1)
    expect(client.addCollection).toHaveBeenCalledWith(
      mockChunterClass.ChatMessage,
      'channel-1',
      'channel-1',
      mockChunterClass.Channel,
      'messages',
      expect.objectContaining({ message: 'announcement' }),
      expect.any(String),
    )
  })

  it('缺 channel_id → 400 BAD_REQUEST', async () => {
    const client = makeMockClient()
    const app = makeApp(client)
    const res = await supertest(app).post('/api/im/post_channel').send({ markdown: 'hi' })

    expect(res.status).toBe(400)
  })
})

describe('POST /api/im/ensure_member', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('用户不存在 → 404 USER_NOT_FOUND', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/ensure_member')
      .send({ channel_id: 'channel-1', username: 'ghost' })

    expect(res.status).toBe(404)
    expect(res.body.code).toBe('USER_NOT_FOUND')
  })

  it('已在成员 → 200 already_member=true, updateDoc 不调用', async () => {
    const client = makeMockClient()
    client.findOne
      // resolveAccountByUsername 2 calls
      .mockResolvedValueOnce({ attachedTo: 'person-1' })
      .mockResolvedValueOnce({ personUuid: 'account-uuid-alice' })
      // findOne Channel
      .mockResolvedValueOnce({
        _id: 'channel-1',
        members: ['account-uuid-alice', 'other-account'],
      })

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/ensure_member')
      .send({ channel_id: 'channel-1', username: 'hr.alice' })

    expect(res.status).toBe(200)
    expect(res.body.data.already_member).toBe(true)
    expect(client.updateDoc).not.toHaveBeenCalled()
  })

  it('不在成员 → updateDoc $push 被调用一次', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-1' })
      .mockResolvedValueOnce({ personUuid: 'account-uuid-bob' })
      .mockResolvedValueOnce({
        _id: 'channel-1',
        members: ['account-uuid-alice'],
      })
    client.updateDoc.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/ensure_member')
      .send({ channel_id: 'channel-1', username: 'zhang.san' })

    expect(res.status).toBe(200)
    expect(res.body.data.already_member).toBe(false)
    expect(client.updateDoc).toHaveBeenCalledTimes(1)
    expect(client.updateDoc).toHaveBeenCalledWith(
      mockChunterClass.Channel,
      'channel-1',
      expect.objectContaining({ _id: 'channel-1' }),
      { $push: { members: 'account-uuid-bob' } },
    )
  })

  it('Channel 不存在 → 404 CHANNEL_NOT_FOUND', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-1' })
      .mockResolvedValueOnce({ personUuid: 'account-uuid-x' })
      .mockResolvedValueOnce(undefined) // Channel 不存在

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/im/ensure_member')
      .send({ channel_id: 'no-such-channel', username: 'hr.alice' })

    expect(res.status).toBe(404)
    expect(res.body.code).toBe('CHANNEL_NOT_FOUND')
  })
})
