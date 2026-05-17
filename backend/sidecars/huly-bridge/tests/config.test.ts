/**
 * huly-bridge sidecar — config.ts 单测
 *
 * 验证：
 * - loadConfig 缺必需 env 时 throw
 * - loadConfig 完整 env 时返回 immutable BridgeConfig
 * - PORT / LOG_LEVEL 无效时 throw
 * - summarizeConfig 脱敏 BRIDGE_TOKEN / SERVER_SECRET
 */

import { describe, expect, it } from 'vitest'

import { loadConfig, summarizeConfig } from '../src/config.js'

function baseValidEnv(): NodeJS.ProcessEnv {
  return {
    BRIDGE_TOKEN: 'test-bridge-token-12345',
    HULY_URL: 'http://huly:8087',
    HULY_ACCOUNTS_URL: 'http://huly-account:3007',
    HULY_WORKSPACE: 'laios',
    SERVER_SECRET: 'test-server-secret-abcdef',
  } as NodeJS.ProcessEnv
}

describe('loadConfig', () => {
  it('完整 env 返回 immutable BridgeConfig', () => {
    const config = loadConfig(baseValidEnv())

    expect(config.port).toBe(7777)
    expect(config.bridgeToken).toBe('test-bridge-token-12345')
    expect(config.hulyUrl).toBe('http://huly:8087')
    expect(config.hulyAccountsUrl).toBe('http://huly-account:3007')
    expect(config.hulyWorkspace).toBe('laios')
    expect(config.serverSecret).toBe('test-server-secret-abcdef')
    expect(config.backendUrl).toBe('http://flow-api:8000')
    expect(config.logLevel).toBe('info')
    expect(config.serviceName).toBe('offboarding-bot')
  })

  it('config 对象是 frozen — 防 mutation', () => {
    const config = loadConfig(baseValidEnv())
    expect(Object.isFrozen(config)).toBe(true)
  })

  it.each(['BRIDGE_TOKEN', 'HULY_URL', 'HULY_ACCOUNTS_URL', 'HULY_WORKSPACE', 'SERVER_SECRET'])(
    '缺 %s 时 throw',
    (missing) => {
      const env = baseValidEnv()
      delete env[missing]
      expect(() => loadConfig(env)).toThrowError(new RegExp(missing))
    },
  )

  it('多个必需 env 缺失时 error 列出全部', () => {
    const env = baseValidEnv()
    delete env.BRIDGE_TOKEN
    delete env.HULY_URL
    expect(() => loadConfig(env)).toThrowError(/BRIDGE_TOKEN.*HULY_URL|HULY_URL.*BRIDGE_TOKEN/)
  })

  it('必需 env 为空字符串时也算缺失', () => {
    const env = { ...baseValidEnv(), BRIDGE_TOKEN: '   ' }
    expect(() => loadConfig(env)).toThrowError(/BRIDGE_TOKEN/)
  })

  it('PORT 可由 env 覆盖', () => {
    const config = loadConfig({ ...baseValidEnv(), PORT: '9999' })
    expect(config.port).toBe(9999)
  })

  it('PORT 非数字时 throw', () => {
    expect(() => loadConfig({ ...baseValidEnv(), PORT: 'abc' })).toThrowError(/PORT/)
  })

  it('PORT 超界（0 / 65536）时 throw', () => {
    expect(() => loadConfig({ ...baseValidEnv(), PORT: '0' })).toThrowError(/PORT/)
    expect(() => loadConfig({ ...baseValidEnv(), PORT: '65536' })).toThrowError(/PORT/)
  })

  it('LOG_LEVEL 可由 env 覆盖（debug / info / warn / error 都合法）', () => {
    for (const level of ['debug', 'info', 'warn', 'error']) {
      const config = loadConfig({ ...baseValidEnv(), LOG_LEVEL: level })
      expect(config.logLevel).toBe(level)
    }
  })

  it('LOG_LEVEL 不合法时 throw', () => {
    expect(() => loadConfig({ ...baseValidEnv(), LOG_LEVEL: 'verbose' })).toThrowError(/LOG_LEVEL/)
  })

  it('BACKEND_URL / SERVICE_NAME 可由 env 覆盖', () => {
    const config = loadConfig({
      ...baseValidEnv(),
      BACKEND_URL: 'http://custom-backend:9000',
      SERVICE_NAME: 'custom-bot',
    })
    expect(config.backendUrl).toBe('http://custom-backend:9000')
    expect(config.serviceName).toBe('custom-bot')
  })
})

describe('summarizeConfig', () => {
  it('脱敏 BRIDGE_TOKEN 与 SERVER_SECRET', () => {
    const config = loadConfig(baseValidEnv())
    const summary = summarizeConfig(config)

    expect(summary.bridgeToken).toBe('***')
    expect(summary.serverSecret).toBe('***')
  })

  it('保留非敏感字段原值', () => {
    const config = loadConfig(baseValidEnv())
    const summary = summarizeConfig(config)

    expect(summary.port).toBe(7777)
    expect(summary.hulyUrl).toBe('http://huly:8087')
    expect(summary.hulyWorkspace).toBe('laios')
    expect(summary.logLevel).toBe('info')
  })
})
