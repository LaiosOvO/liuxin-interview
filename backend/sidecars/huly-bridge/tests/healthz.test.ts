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
vi.mock('@hcengineering/core', () => ({
  systemAccountUuid: '00000000-0000-0000-0000-000000000001',
}))

vi.mock('@hcengineering/platform', () => ({
  setMetadata: vi.fn(),
}))

vi.mock('@hcengineering/server-client', () => ({
  default: {
    metadata: {
      Endpoint: Symbol('serverClient.Endpoint'),
      UserAgent: Symbol('serverClient.UserAgent'),
    },
  },
}))

vi.mock('@hcengineering/server-token', () => ({
  default: {
    metadata: {
      Secret: Symbol('serverToken.Secret'),
      Service: Symbol('serverToken.Service'),
    },
  },
  generateToken: vi.fn(() => 'mock-jwt-token'),
}))

vi.mock('@hcengineering/api-client', () => ({
  connect: vi.fn(),
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

describe('业务路由 stub（Plan 05 实现）', () => {
  it.each([
    ['POST', '/api/im/send-dm'],
    ['POST', '/api/im/send-channel'],
    ['GET', '/api/im/list-channels'],
    ['POST', '/api/doc/create-folder'],
    ['POST', '/api/doc/create-doc'],
    ['POST', '/api/doc/update-doc'],
    ['POST', '/api/doc/link-collaborator'],
  ])('%s %s 带正确 token → 501 NOT_IMPLEMENTED', async (method, path) => {
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
    const res = await supertest(app).post('/api/im/send-dm')
    expect(res.status).toBe(401)
    expect(res.body).toMatchObject({
      ok: false,
      code: 'BRIDGE_TOKEN_MISSING',
    })
  })

  it('/api/* token 不匹配 → 401 BRIDGE_TOKEN_INVALID', async () => {
    const app = createApp(fakeConfig(), createInitialHealthState())
    const res = await supertest(app)
      .post('/api/im/send-dm')
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
