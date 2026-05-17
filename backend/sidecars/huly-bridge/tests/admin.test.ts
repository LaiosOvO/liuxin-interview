/**
 * huly-bridge sidecar — admin.ts 业务路由测试
 *
 * Phase 8 / HULY-08
 *
 * 覆盖（6 用例）：
 * 1. 缺 X-Admin-Token → 403
 * 2. 缺 X-Bridge-Token → 401（即使 X-Admin-Token 对）
 * 3. account 已存在 → 200 skipped=true（兜底幂等：signUpJoin 抛 already exists → login 拿 UUID）
 * 4. account 不存在 → createInvite + signUpJoin 顺序调用 → 200 skipped=false
 * 5. signUp 抛 ACCOUNT_ALREADY_EXISTS → 转 200 skipped=true（同 3 兜底）
 * 6. createInvite 失败 → 400 CREATE_INVITE_FAILED（透明错误）
 */

import express, { type Express } from 'express'
import supertest from 'supertest'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AccountClient } from '@hcengineering/account-client'

import {
  _resetAdminCacheForTests,
  _setTestAccountClientFactory,
  mountAdminRoutes,
} from '../src/admin.js'
import { ADMIN_TOKEN_HEADER, BRIDGE_TOKEN_HEADER, bridgeAuth } from '../src/middleware.js'

import type { BridgeConfig } from '../src/types.js'

// Mock @hcengineering/* — 与 im_routes.test.ts 同模式
vi.mock('@hcengineering/account-client', () => ({
  default: { getClient: () => null },
  getClient: () => null,
}))

const TEST_BRIDGE_TOKEN = 'test-bridge-token-32-chars-aaaa'
const TEST_ADMIN_TOKEN = 'test-admin-token-32-chars-bbbbbb'

function makeConfig(overrides: Partial<BridgeConfig> = {}): BridgeConfig {
  return Object.freeze({
    port: 7777,
    bridgeToken: TEST_BRIDGE_TOKEN,
    hulyUrl: 'http://huly:8087',
    hulyAccountsUrl: 'http://huly-account:3007',
    hulyWorkspace: 'laios',
    serverSecret: 'test-server-secret',
    backendUrl: 'http://flow-api:8000',
    logLevel: 'info' as const,
    serviceName: 'offboarding-bot',
    adminToken: TEST_ADMIN_TOKEN,
    adminEmail: 'admin@huly.local',
    adminPassword: 'admin-password-123',
    ...overrides,
  })
}

/**
 * 构造可控的 mock AccountClient — 测试单独控制每个方法返回值。
 */
interface MockAccountClientCtrl {
  loginMock: ReturnType<typeof vi.fn>
  signUpJoinMock: ReturnType<typeof vi.fn>
  createInviteMock: ReturnType<typeof vi.fn>
  signUpMock: ReturnType<typeof vi.fn>
  selectWorkspaceMock: ReturnType<typeof vi.fn>
  createWorkspaceMock: ReturnType<typeof vi.fn>
}

function makeMockClient(ctrl: MockAccountClientCtrl): AccountClient {
  return {
    login: ctrl.loginMock,
    signUpJoin: ctrl.signUpJoinMock,
    createInvite: ctrl.createInviteMock,
    signUp: ctrl.signUpMock,
    selectWorkspace: ctrl.selectWorkspaceMock,
    createWorkspace: ctrl.createWorkspaceMock,
  } as unknown as AccountClient
}

function makeCtrl(): MockAccountClientCtrl {
  return {
    loginMock: vi.fn(),
    signUpJoinMock: vi.fn(),
    createInviteMock: vi.fn(),
    signUpMock: vi.fn(),
    selectWorkspaceMock: vi.fn(),
    createWorkspaceMock: vi.fn(),
  }
}

/**
 * 构造完整 Express app — 含 bridgeAuth + adminRoutes，模拟生产 stack。
 */
function makeApp(config: BridgeConfig): Express {
  const app = express()
  app.use(express.json())
  app.use(bridgeAuth(config.bridgeToken))
  mountAdminRoutes(app, config)
  return app
}

describe('mountAdminRoutes — ADMIN_TOKEN 未配置时不挂载路由', () => {
  beforeEach(() => {
    _resetAdminCacheForTests()
    _setTestAccountClientFactory(null)
  })

  it('config.adminToken 为空 → admin 路由不挂载（404）', async () => {
    const config = makeConfig({ adminToken: '' })
    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .send({})

    // 路由没挂 → 走到 default 404（无 notFoundHandler 的情况下 express 默认 404）
    expect(res.status).toBe(404)
  })
})

describe('POST /api/admin/signup_join — 双 token 鉴权', () => {
  beforeEach(() => {
    _resetAdminCacheForTests()
    _setTestAccountClientFactory(null)
  })

  it('缺 X-Bridge-Token → 401', async () => {
    const config = makeConfig()
    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({})

    expect(res.status).toBe(401)
    expect(res.body).toMatchObject({ code: 'BRIDGE_TOKEN_MISSING' })
  })

  it('缺 X-Admin-Token（即使 X-Bridge-Token 对）→ 403', async () => {
    const config = makeConfig()
    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .send({
        username: 'hr.alice',
        email: 'hr.alice@demo.local',
        password: 'pwd',
        first_name: 'Alice',
        last_name: 'HR',
      })

    expect(res.status).toBe(403)
    expect(res.body).toMatchObject({ code: 'ADMIN_TOKEN_MISSING' })
  })

  it('X-Admin-Token 不匹配 → 403 ADMIN_TOKEN_INVALID', async () => {
    const config = makeConfig()
    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, 'wrong-token-32-chars-yyyyyyyyyyyy')
      .send({})

    expect(res.status).toBe(403)
    expect(res.body).toMatchObject({ code: 'ADMIN_TOKEN_INVALID' })
  })
})

describe('POST /api/admin/signup_join — 业务逻辑', () => {
  beforeEach(() => {
    _resetAdminCacheForTests()
    _setTestAccountClientFactory(null)
  })

  it('account 不存在 → login + createInvite + signUpJoin 顺序调用 → 200 skipped=false', async () => {
    const config = makeConfig()
    const ctrl = makeCtrl()
    ctrl.loginMock.mockResolvedValueOnce({
      account: 'admin-account-uuid',
      token: 'admin-token-xxx',
    })
    ctrl.createInviteMock.mockResolvedValueOnce('invite-id-12345')
    ctrl.signUpJoinMock.mockResolvedValueOnce({
      account: 'new-user-account-uuid',
      token: 'user-ws-token',
      workspace: 'laios-uuid',
      workspaceUrl: 'laios',
      endpoint: 'ws://transactor',
    })

    _setTestAccountClientFactory(() => makeMockClient(ctrl))

    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({
        username: 'hr.alice',
        email: 'hr.alice@demo.local',
        password: 'pwd123',
        first_name: 'Alice',
        last_name: 'HR',
        role: 'USER',
      })

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({
      ok: true,
      data: { account_uuid: 'new-user-account-uuid', skipped: false },
    })
    // login 至少调用一次（admin login）
    expect(ctrl.loginMock).toHaveBeenCalledWith('admin@huly.local', 'admin-password-123')
    // createInvite 用 admin token client
    expect(ctrl.createInviteMock).toHaveBeenCalledTimes(1)
    expect(ctrl.createInviteMock).toHaveBeenCalledWith(
      expect.any(Number),
      'hr.alice@demo.local',
      1,
      'USER',
    )
    // signUpJoin 用 anonymous client
    expect(ctrl.signUpJoinMock).toHaveBeenCalledWith(
      'hr.alice@demo.local',
      'pwd123',
      'Alice',
      'HR',
      'invite-id-12345',
      'laios',
    )
  })

  it('signUpJoin 抛 already exists → 走 login fallback → 200 skipped=true', async () => {
    const config = makeConfig()
    const ctrl = makeCtrl()
    ctrl.loginMock
      // 第一次 login = admin login
      .mockResolvedValueOnce({ account: 'admin-acc', token: 'admin-tok' })
      // 第二次 login = 兜底用户 login（拿 accountUuid）
      .mockResolvedValueOnce({ account: 'existing-user-uuid', token: 'user-tok' })
    ctrl.createInviteMock.mockResolvedValueOnce('invite-id-22222')
    ctrl.signUpJoinMock.mockRejectedValueOnce(new Error('Account already exists'))

    _setTestAccountClientFactory(() => makeMockClient(ctrl))

    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({
        username: 'zhang.san',
        email: 'zhang.san@demo.local',
        password: 'pwd123',
        first_name: '三',
        last_name: '张',
      })

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({
      ok: true,
      data: { account_uuid: 'existing-user-uuid', skipped: true },
    })
    // login 总共 2 次：admin + 兜底
    expect(ctrl.loginMock).toHaveBeenCalledTimes(2)
  })

  it('已存在但 login 也失败 → 409 ACCOUNT_EXISTS_PASSWORD_MISMATCH', async () => {
    const config = makeConfig()
    const ctrl = makeCtrl()
    ctrl.loginMock
      .mockResolvedValueOnce({ account: 'admin-acc', token: 'admin-tok' })
      // user login 失败
      .mockRejectedValueOnce(new Error('Invalid password'))
    ctrl.createInviteMock.mockResolvedValueOnce('invite-id-33333')
    ctrl.signUpJoinMock.mockRejectedValueOnce(new Error('Account-already-exists'))

    _setTestAccountClientFactory(() => makeMockClient(ctrl))

    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({
        username: 'ghost.user',
        email: 'ghost@demo.local',
        password: 'wrong-pwd',
        first_name: 'Ghost',
        last_name: 'X',
      })

    expect(res.status).toBe(409)
    expect(res.body).toMatchObject({ code: 'ACCOUNT_EXISTS_PASSWORD_MISMATCH' })
  })

  it('createInvite 失败 → 400 CREATE_INVITE_FAILED', async () => {
    const config = makeConfig()
    const ctrl = makeCtrl()
    ctrl.loginMock.mockResolvedValueOnce({ account: 'admin-acc', token: 'admin-tok' })
    ctrl.createInviteMock.mockRejectedValueOnce(new Error('workspace not found'))

    _setTestAccountClientFactory(() => makeMockClient(ctrl))

    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({
        username: 'fin.david',
        email: 'fin.david@demo.local',
        password: 'pwd123',
        first_name: 'David',
        last_name: 'Fin',
      })

    expect(res.status).toBe(400)
    expect(res.body).toMatchObject({ code: 'CREATE_INVITE_FAILED' })
    // signUpJoin 不应被调用
    expect(ctrl.signUpJoinMock).not.toHaveBeenCalled()
  })

  it('signUpJoin 抛非已存在错误 → 400 SIGNUP_JOIN_FAILED', async () => {
    const config = makeConfig()
    const ctrl = makeCtrl()
    ctrl.loginMock.mockResolvedValueOnce({ account: 'admin-acc', token: 'admin-tok' })
    ctrl.createInviteMock.mockResolvedValueOnce('invite-id-44444')
    ctrl.signUpJoinMock.mockRejectedValueOnce(new Error('weak password'))

    _setTestAccountClientFactory(() => makeMockClient(ctrl))

    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({
        username: 'legal.eve',
        email: 'legal.eve@demo.local',
        password: '1',
        first_name: 'Eve',
        last_name: 'Legal',
      })

    expect(res.status).toBe(400)
    expect(res.body).toMatchObject({ code: 'SIGNUP_JOIN_FAILED' })
  })

  it('请求体缺 email → 400 BAD_REQUEST', async () => {
    const config = makeConfig()
    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({ username: 'hr.alice', password: 'pwd', first_name: 'A', last_name: 'B' })

    expect(res.status).toBe(400)
    expect(res.body).toMatchObject({ code: 'BAD_REQUEST' })
  })

  it('admin 凭证缺失 → 500 ADMIN_LOGIN_FAILED', async () => {
    // 显式配 ADMIN_TOKEN 让路由挂上，但 adminEmail/Password 留空
    const config = makeConfig({ adminEmail: '', adminPassword: '' })
    _setTestAccountClientFactory(() => makeMockClient(makeCtrl()))

    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, TEST_ADMIN_TOKEN)
      .send({
        username: 'hr.alice',
        email: 'hr.alice@demo.local',
        password: 'pwd',
        first_name: 'A',
        last_name: 'B',
      })

    expect(res.status).toBe(500)
    expect(res.body).toMatchObject({ code: 'ADMIN_LOGIN_FAILED' })
  })
})

describe('adminAuth middleware — 独立单测（防 timing attack）', () => {
  it('长度不同 token → 不进入字符串比较 → 403', async () => {
    const config = makeConfig()
    const app = makeApp(config)
    const res = await supertest(app)
      .post('/api/admin/signup_join')
      .set(BRIDGE_TOKEN_HEADER, TEST_BRIDGE_TOKEN)
      .set(ADMIN_TOKEN_HEADER, 'too-short')
      .send({})

    expect(res.status).toBe(403)
    expect(res.body).toMatchObject({ code: 'ADMIN_TOKEN_INVALID' })
  })
})
