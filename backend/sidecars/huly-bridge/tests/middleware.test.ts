/**
 * huly-bridge sidecar — middleware.ts 单测
 *
 * 验证：
 * - bridgeAuth：缺 header → 401；token 不匹配 → 401；token 匹配 → 放行
 * - bridgeAuth：/healthz 不需 token（白名单）
 * - notFoundHandler：返回 404 + ErrorResponse envelope
 * - errorHandler：返回 500 + 脱敏后的 error message
 */

import { describe, expect, it, vi } from 'vitest'

import {
  BRIDGE_TOKEN_HEADER,
  bridgeAuth,
  errorHandler,
  notFoundHandler,
} from '../src/middleware.js'

import type { NextFunction, Request, Response } from 'express'

/**
 * MockResponse 的可访问内部状态。
 *
 * 用 type alias 避免 extends Response 时承接 100+ 复杂方法的 signature 冲突。
 */
type MockResponse = Response & {
  _status: number
  _body: unknown
  headersSent: boolean
}

/**
 * 创建 mock express Response —— 链式 status().json() 风格。
 *
 * 用 `as unknown as MockResponse` 故意 bypass 完整 Response 接口（100+ 方法）。
 * 中间件只调 status / json / on / headersSent，无需 mock 全部。
 */
function mockResponse(): MockResponse {
  const internalState = {
    _status: 0 as number,
    _body: undefined as unknown,
    headersSent: false,
  }
  const res = {
    ...internalState,
    on: vi.fn(),
    status(code: number) {
      this._status = code
      return this
    },
    json(body: unknown) {
      this._body = body
      this.headersSent = true
      return this
    },
  }
  return res as unknown as MockResponse
}

/**
 * 创建 mock Request —— 支持 path / header
 */
function mockRequest(opts: { path?: string; headers?: Record<string, string>; method?: string }): Request {
  const headers = opts.headers ?? {}
  return {
    path: opts.path ?? '/api/test',
    method: opts.method ?? 'POST',
    header(name: string) {
      return headers[name.toLowerCase()]
    },
  } as unknown as Request
}

describe('bridgeAuth', () => {
  it('expectedToken 为空时 throw（防配置错误）', () => {
    expect(() => bridgeAuth('')).toThrowError(/BRIDGE_TOKEN/)
    expect(() => bridgeAuth('   ')).toThrowError(/BRIDGE_TOKEN/)
  })

  it('/healthz 公开放行（无需 token）', () => {
    const mw = bridgeAuth('secret-token')
    const req = mockRequest({ path: '/healthz', method: 'GET' })
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    mw(req, res, next)

    expect(next).toHaveBeenCalledTimes(1)
    expect(res._status).toBe(0) // 未 send response
  })

  it('/ 公开放行（无需 token）', () => {
    const mw = bridgeAuth('secret-token')
    const req = mockRequest({ path: '/', method: 'GET' })
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    mw(req, res, next)

    expect(next).toHaveBeenCalledTimes(1)
  })

  it('/api/* 缺 X-Bridge-Token header → 401 BRIDGE_TOKEN_MISSING', () => {
    const mw = bridgeAuth('secret-token')
    const req = mockRequest({ path: '/api/im/send-dm' })
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    mw(req, res, next)

    expect(next).not.toHaveBeenCalled()
    expect(res._status).toBe(401)
    expect(res._body).toEqual({
      ok: false,
      error: expect.stringContaining(BRIDGE_TOKEN_HEADER),
      code: 'BRIDGE_TOKEN_MISSING',
    })
  })

  it('/api/* token 不匹配 → 401 BRIDGE_TOKEN_INVALID', () => {
    const mw = bridgeAuth('secret-token')
    const req = mockRequest({
      path: '/api/im/send-dm',
      headers: { [BRIDGE_TOKEN_HEADER]: 'wrong-token' },
    })
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    mw(req, res, next)

    expect(next).not.toHaveBeenCalled()
    expect(res._status).toBe(401)
    expect(res._body).toEqual({
      ok: false,
      error: expect.stringContaining('不匹配'),
      code: 'BRIDGE_TOKEN_INVALID',
    })
  })

  it('/api/* token 长度不等 → 401 不进入字符串比较（防 timing attack）', () => {
    const mw = bridgeAuth('secret-token-12345')
    const req = mockRequest({
      path: '/api/im/send-dm',
      headers: { [BRIDGE_TOKEN_HEADER]: 'short' },
    })
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    mw(req, res, next)

    expect(next).not.toHaveBeenCalled()
    expect(res._status).toBe(401)
    expect(res._body).toMatchObject({ code: 'BRIDGE_TOKEN_INVALID' })
  })

  it('/api/* token 匹配 → 放行', () => {
    const mw = bridgeAuth('secret-token')
    const req = mockRequest({
      path: '/api/im/send-dm',
      headers: { [BRIDGE_TOKEN_HEADER]: 'secret-token' },
    })
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    mw(req, res, next)

    expect(next).toHaveBeenCalledTimes(1)
    expect(res._status).toBe(0)
  })
})

describe('notFoundHandler', () => {
  it('返回 404 + 含路径与 NOT_FOUND code', () => {
    const req = mockRequest({ path: '/api/unknown', method: 'GET' })
    const res = mockResponse()

    notFoundHandler(req, res)

    expect(res._status).toBe(404)
    expect(res._body).toEqual({
      ok: false,
      error: expect.stringMatching(/未知路径.*GET.*\/api\/unknown/),
      code: 'NOT_FOUND',
    })
  })
})

describe('errorHandler', () => {
  it('Error 实例 → 500 + 包含 error.message', () => {
    const err = new Error('数据库爆炸')
    const req = mockRequest({})
    const res = mockResponse()
    const next = vi.fn() as NextFunction

    // 屏蔽 console.error 噪音
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    errorHandler(err, req, res, next)

    expect(res._status).toBe(500)
    expect(res._body).toEqual({
      ok: false,
      error: '数据库爆炸',
      code: 'INTERNAL_ERROR',
    })
    expect(consoleErrorSpy).toHaveBeenCalled()

    consoleErrorSpy.mockRestore()
  })

  it('非 Error 类型 → 500 + 通用错误信息', () => {
    const req = mockRequest({})
    const res = mockResponse()
    const next = vi.fn() as NextFunction
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    errorHandler('字符串错误', req, res, next)

    expect(res._status).toBe(500)
    expect(res._body).toMatchObject({
      ok: false,
      error: '内部错误',
      code: 'INTERNAL_ERROR',
    })

    consoleErrorSpy.mockRestore()
  })

  it('headersSent 后不再 send（防 double-send）', () => {
    const err = new Error('test')
    const req = mockRequest({})
    const res = mockResponse()
    res.headersSent = true
    const next = vi.fn() as NextFunction
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    errorHandler(err, req, res, next)

    expect(res._status).toBe(0) // 未改 status
    expect(consoleErrorSpy).toHaveBeenCalled() // 但仍打日志

    consoleErrorSpy.mockRestore()
  })
})
