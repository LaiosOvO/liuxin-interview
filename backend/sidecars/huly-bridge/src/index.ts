/**
 * huly-bridge sidecar — Express 应用 entrypoint
 *
 * Phase 8 / HULY-03 + HULY-04
 *
 * 职责：
 * 1. 加载配置（src/config.ts loadConfig）
 * 2. 初始化 Huly SDK metadata（src/auth.ts initAuth）
 * 3. 启动 Express HTTP server（port = config.port = 7777）
 * 4. 后台连 Huly transactor（不阻塞 server 启动；连接状态写 healthState）
 * 5. mount /healthz + /api/im (stub) + /api/doc (stub)
 *
 * 设计要点：
 * - 启动顺序：load env → initAuth → start express → background connect Huly
 * - server 不等 Huly connect 完才 listen — Huly 临时不可达不应让 sidecar 起不来
 *   （NFR-06：sidecar 启动期不卡，Huly 抖动期间 healthz 返回 huly_connected=false）
 * - 业务路由（IM / Doc）在本 plan 仅返回 501，Plan 05 实现
 */

// Huly api-client 同样是 CJS — lazy import 避免启动期 ESM 解析问题
import apiClientModule from '@hcengineering/api-client'
import express, { type Express, type Request, type Response } from 'express'

import type { PlatformClient } from '@hcengineering/api-client'

/**
 * 解出 connect 函数（CJS 默认 export 或顶级）
 */
function getConnect(): (url: string, options: { token: string; workspace: string }) => Promise<PlatformClient> {
  const fn =
    (apiClientModule as { connect?: (...args: unknown[]) => Promise<PlatformClient> }).connect ??
    (apiClientModule as { default?: { connect?: (...args: unknown[]) => Promise<PlatformClient> } })
      .default?.connect
  if (typeof fn !== 'function') {
    throw new Error('huly-bridge: @hcengineering/api-client 未导出 connect — 检查 SDK 版本')
  }
  return fn as (
    url: string,
    options: { token: string; workspace: string },
  ) => Promise<PlatformClient>
}

import { _isAuthInitialized, initAuth, serviceToken } from './auth.js'
import { loadConfig, summarizeConfig } from './config.js'
import {
  bridgeAuth,
  errorHandler,
  notFoundHandler,
  requestLogger,
} from './middleware.js'
import type {
  ApiResponse,
  BridgeConfig,
  ErrorResponse,
  HealthzResponse,
  SuccessResponse,
} from './types.js'

/**
 * 当前 sidecar 版本（与 package.json version 对齐，硬编码避 import .json 复杂度）。
 */
const SIDECAR_VERSION = '0.1.0'

/**
 * 模块级 health state — Huly 连接状态。
 *
 * Express handler 读它返回 /healthz；background connect 写它。
 * 不用类 / Class — 简单 mutable record 即可（仅 1 实例）。
 */
interface HealthState {
  hulyConnected: boolean
  lastConnectAttempt: string | null
  lastError: string | null
  client: PlatformClient | null
}

/**
 * 创建初始 health state（不可在外部 mutate — 通过 updateHealthState 走）。
 */
function createInitialHealthState(): HealthState {
  return {
    hulyConnected: false,
    lastConnectAttempt: null,
    lastError: null,
    client: null,
  }
}

/**
 * 业务路由 stub —— 本 plan 全部返回 501 Not Implemented。
 * Plan 05 会替换为真实实现。
 */
function notImplemented(operation: string) {
  return function notImplementedHandler(_req: Request, res: Response): void {
    const body: ErrorResponse = {
      ok: false,
      error: `${operation} 尚未实现 — 等 Plan 05 实现 Huly TS SDK 路由`,
      code: 'NOT_IMPLEMENTED',
    }
    res.status(501).json(body)
  }
}

/**
 * 创建 Express app — 安装中间件 + 路由。
 *
 * 拆分出来给测试用：测试不需要真起 server / 连 Huly，只需要 app 实例 + injected health state。
 *
 * @param config 已加载的 BridgeConfig
 * @param healthState 共享的 health 状态对象（test 可注入 mock）
 * @returns 配置好的 Express app
 */
export function createApp(config: BridgeConfig, healthState: HealthState): Express {
  const app = express()

  // 全局中间件
  app.use(express.json({ limit: '1mb' }))
  app.use(requestLogger(config.logLevel))
  app.use(bridgeAuth(config.bridgeToken))

  // /healthz — 公开（中间件白名单放行），返回 Huly 连接状态
  app.get('/healthz', (_req: Request, res: Response): void => {
    const body: HealthzResponse = {
      ok: true,
      huly_connected: healthState.hulyConnected,
      version: SIDECAR_VERSION,
      uptime: Math.round(process.uptime()),
      last_connect_attempt: healthState.lastConnectAttempt,
      last_error: healthState.lastError,
    }
    res.status(200).json(body)
  })

  // 根路径 — 简单 banner
  app.get('/', (_req: Request, res: Response): void => {
    const body: SuccessResponse<{ name: string; version: string }> = {
      ok: true,
      data: { name: 'huly-bridge', version: SIDECAR_VERSION },
    }
    res.status(200).json(body)
  })

  // ==========================================================================
  // 业务路由 stub —— Plan 05 替换为真实实现
  // ==========================================================================
  // IM 路由
  app.post('/api/im/send-dm', notImplemented('send-dm'))
  app.post('/api/im/send-channel', notImplemented('send-channel'))
  app.get('/api/im/list-channels', notImplemented('list-channels'))

  // Doc 路由
  app.post('/api/doc/create-folder', notImplemented('create-folder'))
  app.post('/api/doc/create-doc', notImplemented('create-doc'))
  app.post('/api/doc/update-doc', notImplemented('update-doc'))
  app.post('/api/doc/link-collaborator', notImplemented('link-collaborator'))

  // 404 + error handler 必须放最后
  app.use(notFoundHandler)
  app.use(errorHandler)

  return app
}

/**
 * 后台尝试连 Huly transactor — 失败不阻塞 server。
 *
 * 行为：
 * - 调 initAuth → serviceToken → connect(hulyUrl, {token, workspace})
 * - 成功：写 healthState.client + hulyConnected=true
 * - 失败：写 lastError + hulyConnected=false（保留 client=null）
 *
 * @param config BridgeConfig
 * @param healthState 共享 health state
 */
export async function connectHulyInBackground(
  config: BridgeConfig,
  healthState: HealthState,
): Promise<void> {
  healthState.lastConnectAttempt = new Date().toISOString()

  try {
    // 确保 auth 已 init（idempotent — initAuth 重复调安全）
    if (!_isAuthInitialized()) {
      initAuth(config)
    }
    const token = serviceToken()

    const connect = getConnect()
    const client = await connect(config.hulyUrl, {
      token,
      workspace: config.hulyWorkspace,
    })

    healthState.client = client
    healthState.hulyConnected = true
    healthState.lastError = null
    console.log(`[huly-bridge] ✓ 已连上 Huly transactor: ${config.hulyUrl} (workspace=${config.hulyWorkspace})`)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    healthState.client = null
    healthState.hulyConnected = false
    healthState.lastError = message
    console.warn(
      `[huly-bridge] ⚠ 连 Huly 失败（healthz 会反映）: ${message}`,
    )
  }
}

/**
 * Sidecar 主启动函数。
 *
 * 可被测试通过 import 调用（虽然测试一般用 createApp 不起 server）。
 */
export async function main(): Promise<void> {
  // 1. 加载配置（fail fast）
  const config = loadConfig()
  console.log('[huly-bridge] 启动配置:', summarizeConfig(config))

  // 2. 初始化 Huly SDK metadata
  initAuth(config)
  console.log('[huly-bridge] Huly SDK metadata 已初始化')

  // 3. 创建 health state + Express app
  const healthState = createInitialHealthState()
  const app = createApp(config, healthState)

  // 4. 起 server（不等 Huly 连接成功）
  const server = app.listen(config.port, () => {
    console.log(`[huly-bridge] HTTP server listening on :${config.port}`)
  })

  // 5. 后台连 Huly（非阻塞）
  void connectHulyInBackground(config, healthState)

  // 6. 优雅关停
  const shutdown = (signal: string): void => {
    console.log(`[huly-bridge] 收到 ${signal} —— 关停 server...`)
    server.close((err?: Error) => {
      if (err) {
        console.error('[huly-bridge] server.close 出错:', err)
        process.exit(1)
      }
      console.log('[huly-bridge] server 已关停')
      process.exit(0)
    })
    // 兜底：10s 还没关掉就强退
    setTimeout(() => {
      console.warn('[huly-bridge] 关停超时，强制退出')
      process.exit(1)
    }, 10_000).unref()
  }
  process.on('SIGTERM', () => shutdown('SIGTERM'))
  process.on('SIGINT', () => shutdown('SIGINT'))
}

// 仅当作为 entrypoint 直接执行时才 main()
// 测试 import 本模块不会触发 main
const isDirectRun =
  typeof process !== 'undefined' &&
  process.argv[1] !== undefined &&
  process.argv[1].endsWith('index.ts')

if (isDirectRun) {
  main().catch((err: unknown) => {
    console.error('[huly-bridge] 启动失败:', err)
    process.exit(1)
  })
}

export type { HealthState }
export { createInitialHealthState }
