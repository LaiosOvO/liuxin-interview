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
 * X-Admin-Token header 名（Plan 06 admin API 用 — 第二道保护层）。
 *
 * 设计动机：BRIDGE_TOKEN 是 Python backend ↔ sidecar 的常用通信 token，
 * 普通业务路由都用它。但 admin API（signUp 创账号 / 加 workspace）一旦
 * 被业务侧 LLM 误调，会污染 Huly account 数据。
 *
 * 用 ADMIN_TOKEN 做第二道保护，确保只有 seed 脚本（手动注入）才能调 admin 路由。
 */
export const ADMIN_TOKEN_HEADER = 'x-admin-token'

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
 * 创建 Admin Token 鉴权中间件（Plan 06）。
 *
 * 用法（必须挂在 bridgeAuth 之后）：
 *   app.use('/api/admin', bridgeAuth(token), adminAuth(adminToken), adminRouter)
 *
 * 行为：
 * - 缺 X-Admin-Token → 403 (ADMIN_TOKEN_MISSING)
 * - X-Admin-Token 不匹配 → 403 (ADMIN_TOKEN_INVALID)
 * - 校验通过 → 放行
 *
 * 注意：
 * - expected 为空字符串时 throw（fail fast，防误配开放接口）
 * - 与 bridgeAuth 同一 timing-attack 防御（长度先判 + 字面比较）
 *
 * @param expectedToken 期望的 admin token（来自 ADMIN_TOKEN env）
 * @returns Express 中间件函数
 */
export function adminAuth(expectedToken: string) {
  if (!expectedToken || expectedToken.trim() === '') {
    throw new Error('huly-bridge: adminAuth(expectedToken) 不能为空 — 检查 ADMIN_TOKEN env')
  }

  return function adminAuthMiddleware(req: Request, res: Response, next: NextFunction): void {
    const presented = req.header(ADMIN_TOKEN_HEADER)

    if (presented === undefined || presented === null) {
      const body: ErrorResponse = {
        ok: false,
        error: `缺少 ${ADMIN_TOKEN_HEADER} header`,
        code: 'ADMIN_TOKEN_MISSING',
      }
      res.status(403).json(body)
      return
    }

    if (presented.length !== expectedToken.length || presented !== expectedToken) {
      const body: ErrorResponse = {
        ok: false,
        error: `${ADMIN_TOKEN_HEADER} 不匹配`,
        code: 'ADMIN_TOKEN_INVALID',
      }
      res.status(403).json(body)
      return
    }

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
