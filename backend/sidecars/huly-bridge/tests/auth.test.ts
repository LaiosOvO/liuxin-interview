/**
 * huly-bridge sidecar — auth.ts 单测
 *
 * 验证：
 * - serviceToken() 在 initAuth 前调用应 throw
 * - initAuth + serviceToken 返回非空 JWT 字符串
 * - serviceToken 多次调用稳定（同 secret 应可重复签）
 *
 * 注意：本测试 mock @hcengineering/* 包以避免真实 SDK 依赖（CI 无 npm install 也能跑）。
 * 真实集成测试在 Plan 05 跑（连真 Huly stack）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock @hcengineering/* 包（避免 vitest 真去 resolve 不存在的 node_modules）
// 注意：auth.ts 用 `import xxx from '...'` default import，并 lazy lookup default + 顶级两种情况
// 所以 mock 必须挂 default 字段（vitest 会自动把 module 包成 { default: ... }）
vi.mock('@hcengineering/core', () => ({
  default: {
    systemAccountUuid: '00000000-0000-0000-0000-000000000001',
  },
  systemAccountUuid: '00000000-0000-0000-0000-000000000001',
}))

vi.mock('@hcengineering/platform', () => {
  const setMetadataMock = vi.fn()
  return {
    default: {
      setMetadata: setMetadataMock,
    },
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
  // 简单 fake generateToken — 返回 mock 的 JWT-like 字符串
  // 真实 generateToken 用 HMAC-SHA256 签 JWT；此处只校验调用契约（accountUuid / workspaceUuid / extra）
  const generateTokenMock = vi.fn(
    (accountUuid: string, workspaceUuid: string | undefined, extra: Record<string, unknown>) => {
      const payload = Buffer.from(
        JSON.stringify({ accountUuid, workspaceUuid: workspaceUuid ?? null, extra }),
      ).toString('base64url')
      return `mock-jwt.${payload}.sig`
    },
  )

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

// 必须在 mock 之后 import — 否则 import 顺序问题
const { initAuth, serviceToken, _resetAuthForTests, _isAuthInitialized } = await import(
  '../src/auth.js'
)
const { loadConfig } = await import('../src/config.js')
const platformModule = (await import('@hcengineering/platform')) as unknown as {
  setMetadata: ReturnType<typeof vi.fn>
}
const setMetadata = platformModule.setMetadata
const serverTokenModule = (await import('@hcengineering/server-token')) as unknown as {
  generateToken: ReturnType<typeof vi.fn>
}

function fakeConfig() {
  return loadConfig({
    BRIDGE_TOKEN: 'test-bridge-token',
    HULY_URL: 'http://huly:8087',
    HULY_ACCOUNTS_URL: 'http://huly-account:3007',
    HULY_WORKSPACE: 'laios',
    SERVER_SECRET: 'test-server-secret',
  } as NodeJS.ProcessEnv)
}

describe('auth', () => {
  beforeEach(() => {
    _resetAuthForTests()
    vi.clearAllMocks()
  })

  afterEach(() => {
    _resetAuthForTests()
  })

  describe('initAuth', () => {
    it('调用 setMetadata 4 次（serverToken Secret + Service + serverClient Endpoint + UserAgent）', () => {
      const config = fakeConfig()
      initAuth(config)
      expect(setMetadata).toHaveBeenCalledTimes(4)
    })

    it('设置 _isAuthInitialized = true', () => {
      expect(_isAuthInitialized()).toBe(false)
      initAuth(fakeConfig())
      expect(_isAuthInitialized()).toBe(true)
    })

    it('重复调用 idempotent —— 不抛错', () => {
      const config = fakeConfig()
      expect(() => {
        initAuth(config)
        initAuth(config)
      }).not.toThrow()
      expect(_isAuthInitialized()).toBe(true)
    })
  })

  describe('serviceToken', () => {
    it('未 initAuth 时调用应 throw', () => {
      expect(() => serviceToken()).toThrowError(/initAuth/)
    })

    it('initAuth 后返回非空字符串', () => {
      initAuth(fakeConfig())
      const token = serviceToken()
      expect(typeof token).toBe('string')
      expect(token.length).toBeGreaterThan(0)
    })

    it('调用 generateToken 时 accountUuid = systemAccountUuid', () => {
      initAuth(fakeConfig())
      serviceToken()
      expect(serverTokenModule.generateToken).toHaveBeenCalledTimes(1)
      const [accountUuid] = serverTokenModule.generateToken.mock.calls[0]
      expect(accountUuid).toBe('00000000-0000-0000-0000-000000000001')
    })

    it('调用 generateToken 时 workspaceUuid = undefined（service token 不绑 workspace）', () => {
      initAuth(fakeConfig())
      serviceToken()
      const [, workspaceUuid] = serverTokenModule.generateToken.mock.calls[0]
      expect(workspaceUuid).toBeUndefined()
    })

    it('调用 generateToken 时 extra.service = config.serviceName', () => {
      initAuth(fakeConfig())
      serviceToken()
      const [, , extra] = serverTokenModule.generateToken.mock.calls[0]
      expect(extra).toEqual({ service: 'offboarding-bot' })
    })

    it('多次调用稳定返回有效 token', () => {
      initAuth(fakeConfig())
      const t1 = serviceToken()
      const t2 = serviceToken()
      expect(t1).toBeTruthy()
      expect(t2).toBeTruthy()
      // mock generateToken 是纯函数，同参应返回同结果
      expect(t1).toBe(t2)
    })

    it('custom SERVICE_NAME 时 extra.service 跟着变', () => {
      const config = loadConfig({
        BRIDGE_TOKEN: 't',
        HULY_URL: 'h',
        HULY_ACCOUNTS_URL: 'a',
        HULY_WORKSPACE: 'w',
        SERVER_SECRET: 's',
        SERVICE_NAME: 'my-custom-service',
      } as NodeJS.ProcessEnv)
      initAuth(config)
      serviceToken()
      const [, , extra] = serverTokenModule.generateToken.mock.calls[0]
      expect(extra).toEqual({ service: 'my-custom-service' })
    })
  })
})
