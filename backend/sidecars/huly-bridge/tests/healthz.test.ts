/**
 * huly-bridge sidecar — /healthz endpoint 集成测试
 *
 * 验证：
 * - GET /healthz 不需 X-Bridge-Token（公开）
 * - GET /healthz 返回 200 + huly_connected / version / uptime / last_error
 * - hulyConnected=true 时 last_error=null
 * - hulyConnected=false 时 last_error 显示错误
 * - 业务路由 stub 返回 501 NOT_IMPLEMENTED
 *
 * 用 supertest 真起 express app 测；不连真 Huly。
 */

import { describe, expect, it, vi } from 'vitest'

// Mock @hcengineering/* 包（与 auth.test.ts 一致）— 防 vitest 真去 resolve
// 关键：default + 顶级都挂，兼容 source code lazy lookup 两种路径
vi.mock('@hcengineering/core', () => ({
  default: {
    systemAccountUuid: '00000000-0000-0000-0000-000000000001',
  },
  systemAccountUuid: '00000000-0000-0000-0000-000000000001',
}))

vi.mock('@hcengineering/platform', () => {
  const setMetadataMock = vi.fn()
  return {
    default: { setMetadata: setMetadataMock },
    setMetadata: setMetadataMock,
  }
})

vi.mock('@hcengineering/server-client', () => ({
  default: {
    metadata: {
      Endpoint: Symbol('serverClient.Endpoint'),
      UserAgent: Symbol('serverClient.UserAgent'),
    },
  },
}))

vi.mock('@hcengineering/server-token', () => {
  const generateTokenMock = vi.fn(() => 'mock-jwt-token')
  return {
    default: {
      metadata: {
        Secret: Symbol('serverToken.Secret'),
        Service: Symbol('serverToken.Service'),
      },
      generateToken: generateTokenMock,
    },
    generateToken: generateTokenMock,
  }
})

vi.mock('@hcengineering/api-client', () => {
  const connectMock = vi.fn()
  return {
    default: { connect: connectMock },
    connect: connectMock,
  }
})

// Plan 05 — index.ts 现在 import doc.js 间接依赖 @hcengineering/document（npm 公网无 0.7.423）
// 必须 mock 才能让 vitest 解析（运行时同样靠 lookup helper fallback）
vi.mock('@hcengineering/document', () => ({
  default: {
    class: {
      Teamspace: Symbol('document.class.Teamspace'),
      Document: Symbol('document.class.Document'),
    },
  },
  class: {
    Teamspace: Symbol('document.class.Teamspace'),
    Document: Symbol('document.class.Document'),
  },
}))

// im.ts / listener.ts 依赖
vi.mock('@hcengineering/chunter', () => ({
  default: {
    class: {
      DirectMessage: Symbol('chunter.class.DirectMessage'),
      Channel: Symbol('chunter.class.Channel'),
      ChatMessage: Symbol('chunter.class.ChatMessage'),
    },
  },
  class: {
    DirectMessage: Symbol('chunter.class.DirectMessage'),
    Channel: Symbol('chunter.class.Channel'),
    ChatMessage: Symbol('chunter.class.ChatMessage'),
  },
}))

vi.mock('@hcengineering/contact', () => ({
  default: {
    class: { SocialIdentity: Symbol('contact.class.SocialIdentity') },
    mixin: { Employee: Symbol('contact.mixin.Employee') },
  },
  class: { SocialIdentity: Symbol('contact.class.SocialIdentity') },
  mixin: { Employee: Symbol('contact.mixin.Employee') },
}))

const { createApp, createInitialHealthState } = await import('../src/index.js')
const { loadConfig } = await import('../src/config.js')
const { BRIDGE_TOKEN_HEADER } = await import('../src/middleware.js')

// 用动态 import + supertest 避免 ESM/CJS 兼容问题
const supertest = (await import('supertest')).default

function fakeConfig() {
  return loadConfig({
    BRIDGE_TOKEN: 'test-bridge-token',
    HULY_URL: 'http://huly:8087',
    HULY_ACCOUNTS_URL: 'http://huly-account:3007',
    HULY_WORKSPACE: 'laios',
    SERVER_SECRET: 'test-server-secret',
    LOG_LEVEL: 'warn', // 测试不要 noisy
  } as NodeJS.ProcessEnv)
}

describe('GET /healthz', () => {
  it('不需 X-Bridge-Token —— 公开放行返回 200', async () => {
    const config = fakeConfig()
    const healthState = createInitialHealthState()
    const app = createApp(config, healthState)

    const res = await supertest(app).get('/healthz')

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({
      ok: true,
      huly_connected: false,
      version: expect.any(String),
      uptime: expect.any(Number),
      last_connect_attempt: null,
      last_error: null,
    })
  })

  it('healthState.hulyConnected=true 时反映在 response', async () => {
    const config = fakeConfig()
    const healthState = createInitialHealthState()
    healthState.hulyConnected = true
    healthState.lastConnectAttempt = '2026-05-17T10:00:00Z'
    const app = createApp(config, healthState)

    const res = await supertest(app).get('/healthz')

    expect(res.status).toBe(200)
    expect(res.body.huly_connected).toBe(true)
    expect(res.body.last_connect_attempt).toBe('2026-05-17T10:00:00Z')
    expect(res.body.last_error).toBeNull()
  })

  it('healthState.lastError 反映在 response', async () => {
    const config = fakeConfig()
    const healthState = createInitialHealthState()
    healthState.hulyConnected = false
    healthState.lastError = 'connection refused'
    healthState.lastConnectAttempt = '2026-05-17T10:01:00Z'
    const app = createApp(config, healthState)

    const res = await supertest(app).get('/healthz')

    expect(res.status).toBe(200)
    expect(res.body.huly_connected).toBe(false)
    expect(res.body.last_error).toBe('connection refused')
  })
})

describe('GET / (banner)', () => {
  it('返回 200 + name + version（不需 token）', async () => {
    const app = createApp(fakeConfig(), createInitialHealthState())

    const res = await supertest(app).get('/')

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({
      ok: true,
      data: {
        name: 'huly-bridge',
        version: expect.any(String),
      },
    })
  })
})

describe('业务路由 — Plan 05 真实现 / Plan 04 旧 stub 保留', () => {
  // Plan 05 — Huly 未就绪时业务路由返回 503 HULY_NOT_READY
  // （healthState.client === null 表示 connectHulyInBackground 还没成功）
  it.each([
    ['POST', '/api/im/send_dm'],
    ['POST', '/api/im/post_channel'],
    ['POST', '/api/im/ensure_member'],
    ['POST', '/api/doc/create_space'],
    ['POST', '/api/doc/create_doc'],
    ['GET', '/api/doc/list_in_space'],
    ['DELETE', '/api/doc/document'],
    ['DELETE', '/api/doc/space'],
  ])('%s %s 带正确 token + Huly 未就绪 → 503 HULY_NOT_READY', async (method, path) => {
    const app = createApp(fakeConfig(), createInitialHealthState())
    const lower = method.toLowerCase() as 'get' | 'post' | 'delete'
    const res = await supertest(app)
      [lower](path)
      .set(BRIDGE_TOKEN_HEADER, 'test-bridge-token')

    expect(res.status).toBe(503)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'HULY_NOT_READY',
    })
  })

  // Plan 04 旧 stub 路径（短横线版）保留，返回 501
  it.each([
    ['POST', '/api/im/send-dm'],
    ['POST', '/api/im/send-channel'],
    ['GET', '/api/im/list-channels'],
  ])('%s %s（Plan 04 旧 stub 路径）→ 501 NOT_IMPLEMENTED', async (method, path) => {
    const app = createApp(fakeConfig(), createInitialHealthState())
    const lower = method.toLowerCase() as 'get' | 'post'
    const res = await supertest(app)
      [lower](path)
      .set(BRIDGE_TOKEN_HEADER, 'test-bridge-token')

    expect(res.status).toBe(501)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'NOT_IMPLEMENTED',
    })
  })

  it('/api/* 缺 token → 401 BRIDGE_TOKEN_MISSING', async () => {
    const app = createApp(fakeConfig(), createInitialHealthState())
    const res = await supertest(app).post('/api/im/send_dm')
    expect(res.status).toBe(401)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'BRIDGE_TOKEN_MISSING',
    })
  })

  it('/api/* token 不匹配 → 401 BRIDGE_TOKEN_INVALID', async () => {
    const app = createApp(fakeConfig(), createInitialHealthState())
    const res = await supertest(app)
      .post('/api/im/send_dm')
      .set(BRIDGE_TOKEN_HEADER, 'wrong-token')
    expect(res.status).toBe(401)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'BRIDGE_TOKEN_INVALID',
    })
  })
})

describe('404 兜底', () => {
  it('未知路径带正确 token → 404 NOT_FOUND', async () => {
    const app = createApp(fakeConfig(), createInitialHealthState())
    const res = await supertest(app)
      .get('/api/unknown-endpoint')
      .set(BRIDGE_TOKEN_HEADER, 'test-bridge-token')

    expect(res.status).toBe(404)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'NOT_FOUND',
    })
  })
})
