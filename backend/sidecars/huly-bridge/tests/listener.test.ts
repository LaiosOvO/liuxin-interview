/**
 * huly-bridge sidecar — listener.ts 反向 chat 订阅测试
 *
 * Phase 8 / HULY-05
 *
 * 覆盖：
 * - processOneMessage: 跳自己 (modifiedBy === botAccount) → 不 fetch
 * - processOneMessage: 正常消息 → fetch 1 次，body 含 X-Bridge-Token + payload
 * - processOneMessage: fetch 异常 → 仅 log + 不抛
 * - mapChannelType: DirectMessage → 'D'，Channel → 'O'，PrivateChannel → 'P'
 * - reverseLookupUsername: 找到 Employee + SocialIdentity → 返回 username
 * - reverseLookupUsername: SocialIdentity 缺 key → 返回 undefined
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mockChunterClass = {
  DirectMessage: Symbol('chunter.class.DirectMessage'),
  Channel: Symbol('chunter.class.Channel'),
  ChatMessage: Symbol('chunter.class.ChatMessage'),
}

const mockContactClass = {
  SocialIdentity: Symbol('contact.class.SocialIdentity'),
}

const mockContactMixin = {
  Employee: Symbol('contact.mixin.Employee'),
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

let processOneMessage: typeof import('../src/listener.js').processOneMessage
let mapChannelType: typeof import('../src/listener.js').mapChannelType
let reverseLookupUsername: typeof import('../src/listener.js').reverseLookupUsername

beforeAll(async () => {
  const mod = await import('../src/listener.js')
  processOneMessage = mod.processOneMessage
  mapChannelType = mod.mapChannelType
  reverseLookupUsername = mod.reverseLookupUsername
})

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

const baseConfig = Object.freeze({
  port: 7777,
  bridgeToken: 'secret-bridge-token',
  hulyUrl: 'http://huly:8087',
  hulyAccountsUrl: 'http://huly:3007',
  hulyWorkspace: 'laios',
  serverSecret: 'server-secret',
  backendUrl: 'http://flow-api:8000',
  logLevel: 'info' as const,
  serviceName: 'offboarding-bot',
})

describe('mapChannelType', () => {
  it('DirectMessage → D', () => {
    expect(mapChannelType('chunter:class:DirectMessage')).toBe('D')
  })

  it('Channel → O', () => {
    expect(mapChannelType('chunter:class:Channel')).toBe('O')
  })

  it('PrivateChannel → P', () => {
    expect(mapChannelType('chunter:class:PrivateChannel')).toBe('P')
  })

  it('未知 → O 默认', () => {
    expect(mapChannelType('chunter:class:UnknownThing')).toBe('O')
  })
})

describe('reverseLookupUsername', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('Employee + SocialIdentity 都找到 → 返回 username', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ _id: 'person-1' }) // Employee
      .mockResolvedValueOnce({ key: 'email:hr.alice@demo.local' }) // SocialIdentity

    const result = await reverseLookupUsername(
      client as unknown as Parameters<typeof reverseLookupUsername>[0],
      'account-uuid-alice',
    )

    expect(result).toBe('hr.alice')
  })

  it('Employee 找不到 → undefined', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce(undefined)

    const result = await reverseLookupUsername(
      client as unknown as Parameters<typeof reverseLookupUsername>[0],
      'account-uuid-ghost',
    )

    expect(result).toBeUndefined()
  })

  it('SocialIdentity 缺 key → undefined', async () => {
    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ _id: 'person-1' })
      .mockResolvedValueOnce({ key: undefined })

    const result = await reverseLookupUsername(
      client as unknown as Parameters<typeof reverseLookupUsername>[0],
      'account-uuid-alice',
    )

    expect(result).toBeUndefined()
  })
})

describe('processOneMessage', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal('fetch', fetchMock)
  })

  it('modifiedBy === botAccount → 跳过（不 fetch）', async () => {
    const client = makeMockClient()
    const msg = {
      _id: 'msg-1',
      modifiedBy: BOT_ACCOUNT, // 自己发的
      attachedTo: 'channel-1',
      attachedToClass: 'chunter:class:Channel',
      message: 'bot 自己的消息',
      createdOn: Date.now(),
    }

    const result = await processOneMessage(
      client as unknown as Parameters<typeof processOneMessage>[0],
      msg,
      baseConfig,
      BOT_ACCOUNT,
    )

    expect(result).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('正常消息 → fetch 1 次，body 含 X-Bridge-Token 与 payload', async () => {
    const client = makeMockClient()
    // reverseLookupUsername 走 2 次 findOne
    client.findOne
      .mockResolvedValueOnce({ _id: 'person-1' })
      .mockResolvedValueOnce({ key: 'email:zhang.san@demo.local' })

    const msg = {
      _id: 'msg-2',
      modifiedBy: 'account-uuid-zhang',
      attachedTo: 'dm-1',
      attachedToClass: 'chunter:class:DirectMessage',
      message: '我要离职',
      createdOn: 1700000000000,
    }

    const result = await processOneMessage(
      client as unknown as Parameters<typeof processOneMessage>[0],
      msg,
      baseConfig,
      BOT_ACCOUNT,
    )

    expect(result).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('http://flow-api:8000/api/internal/huly/event')
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Bridge-Token']).toBe('secret-bridge-token')
    expect(opts.headers['Content-Type']).toBe('application/json')
    const body = JSON.parse(opts.body)
    expect(body).toMatchObject({
      sender_account: 'account-uuid-zhang',
      sender_username: 'zhang.san',
      channel_id: 'dm-1',
      message: '我要离职',
      channel_type: 'D',
    })
  })

  it('fetch 异常 → 仅 log，不抛', async () => {
    fetchMock.mockRejectedValueOnce(new Error('network unreachable'))
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ _id: 'person-1' })
      .mockResolvedValueOnce({ key: 'email:hr.alice@demo.local' })

    const msg = {
      _id: 'msg-3',
      modifiedBy: 'account-uuid-alice',
      attachedTo: 'channel-x',
      attachedToClass: 'chunter:class:Channel',
      message: 'test',
      createdOn: 1700000001000,
    }

    let didThrow = false
    let result = false
    try {
      result = await processOneMessage(
        client as unknown as Parameters<typeof processOneMessage>[0],
        msg,
        baseConfig,
        BOT_ACCOUNT,
      )
    } catch {
      didThrow = true
    }

    expect(didThrow).toBe(false)
    expect(result).toBe(false)
    expect(consoleWarnSpy).toHaveBeenCalled()

    consoleWarnSpy.mockRestore()
  })

  it('fetch 返回非 2xx → log warn + 返回 false', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 })
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const client = makeMockClient()
    client.findOne
      .mockResolvedValueOnce({ _id: 'person-1' })
      .mockResolvedValueOnce({ key: 'email:hr.alice@demo.local' })

    const msg = {
      _id: 'msg-4',
      modifiedBy: 'account-uuid-alice',
      attachedTo: 'channel-y',
      attachedToClass: 'chunter:class:Channel',
      message: 'test',
      createdOn: 1700000002000,
    }

    const result = await processOneMessage(
      client as unknown as Parameters<typeof processOneMessage>[0],
      msg,
      baseConfig,
      BOT_ACCOUNT,
    )

    expect(result).toBe(false)
    expect(consoleWarnSpy).toHaveBeenCalled()
    consoleWarnSpy.mockRestore()
  })
})
