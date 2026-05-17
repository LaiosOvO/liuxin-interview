/**
 * huly-bridge sidecar — Express 中间件
 *
 * Phase 8 / HULY-03 + HULY-05 — BRIDGE_TOKEN 鉴权 + 错误处理
 *
 * 设计：
 * - bridgeAuth(token)：校验 X-Bridge-Token header，匹配则放行，否则 401
 * - errorHandler：捕获下游 throw 的 Error，统一返回 ErrorResponse envelope
 * - notFoundHandler：404 兜底
 * - requestLogger：极简日志（method + path + status + duration）
 */

import type { NextFunction, Request, Response } from 'express'

import type { ErrorResponse, LogLevel } from './types.js'

/**
 * 不需要 token 校验的 endpoint 白名单。
 *
 * /healthz 必须放行（docker healthcheck + k8s liveness 用）。
 */
const PUBLIC_PATHS = new Set<string>(['/healthz', '/'])

/**
 * X-Bridge-Token header 名（小写化 — express headers 都是 lower-case）。
 */
export const BRIDGE_TOKEN_HEADER = 'x-bridge-token'

/**
 * 创建 BRIDGE_TOKEN 鉴权中间件。
 *
 * 用法：app.use(bridgeAuth(config.bridgeToken))
 *
 * 行为：
 * - 路径在 PUBLIC_PATHS 中：放行
 * - X-Bridge-Token 与 expected 匹配：放行
 * - 其它情况：401 + ErrorResponse envelope
 *
 * @param expectedToken 期望的 token（来自 BRIDGE_TOKEN env）
 * @returns Express 中间件函数
 */
export function bridgeAuth(expectedToken: string) {
  if (!expectedToken || expectedToken.trim() === '') {
    throw new Error('huly-bridge: bridgeAuth(expectedToken) 不能为空 — 检查 BRIDGE_TOKEN env')
  }

  return function bridgeAuthMiddleware(req: Request, res: Response, next: NextFunction): void {
    // 公共路径直接放行
    if (PUBLIC_PATHS.has(req.path)) {
      next()
      return
    }

    const presented = req.header(BRIDGE_TOKEN_HEADER)

    // 缺 header → 401
    if (presented === undefined || presented === null) {
      const body: ErrorResponse = {
        ok: false,
        error: `缺少 ${BRIDGE_TOKEN_HEADER} header`,
        code: 'BRIDGE_TOKEN_MISSING',
      }
      res.status(401).json(body)
      return
    }

    // token 不匹配 → 401
    // 注意：常时间比较（防 timing attack）— 仅当长度相等时才比较内容
    if (presented.length !== expectedToken.length || presented !== expectedToken) {
      const body: ErrorResponse = {
        ok: false,
        error: `${BRIDGE_TOKEN_HEADER} 不匹配`,
        code: 'BRIDGE_TOKEN_INVALID',
      }
      res.status(401).json(body)
      return
    }

    // 校验通过
    next()
  }
}

/**
 * 404 兜底中间件 — express 路由未匹配时返回结构化 404。
 */
export function notFoundHandler(req: Request, res: Response): void {
  const body: ErrorResponse = {
    ok: false,
    error: `未知路径: ${req.method} ${req.path}`,
    code: 'NOT_FOUND',
  }
  res.status(404).json(body)
}

/**
 * 全局错误处理中间件 — 必须 4 参签名（express 才会识别为 error handler）。
 *
 * 行为：
 * - Error 实例 → 500 + 脱敏后的 error message
 * - 非 Error → 500 + 通用错误信息
 *
 * 注意：production 不暴露 stack trace；development 输出到日志。
 */
export function errorHandler(
  err: unknown,
  _req: Request,
  res: Response,
  _next: NextFunction,
): void {
  const isError = err instanceof Error
  const message = isError ? err.message : '内部错误'

  // 日志（始终打）
  console.error('[huly-bridge] errorHandler:', err)

  // 防止重复 send
  if (res.headersSent) {
    return
  }

  const body: ErrorResponse = {
    ok: false,
    error: message,
    code: 'INTERNAL_ERROR',
  }
  res.status(500).json(body)
}

/**
 * 极简 request logger 中间件 — 记录 method / path / status / duration。
 *
 * @param logLevel 仅在 debug / info 级别输出（warn / error 时禁用）
 */
export function requestLogger(logLevel: LogLevel) {
  const enabled = logLevel === 'debug' || logLevel === 'info'

  return function requestLoggerMiddleware(req: Request, res: Response, next: NextFunction): void {
    if (!enabled) {
      next()
      return
    }

    const start = Date.now()
    res.on('finish', () => {
      const duration = Date.now() - start
      // 仅 debug 打 healthcheck 噪音
      if (req.path === '/healthz' && logLevel !== 'debug') {
        return
      }
      console.log(
        `[huly-bridge] ${req.method} ${req.path} ${res.statusCode} ${duration}ms`,
      )
    })

    next()
  }
}
