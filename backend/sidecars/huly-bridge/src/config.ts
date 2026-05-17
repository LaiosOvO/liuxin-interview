/**
 * huly-bridge sidecar — 环境变量解析 + 配置加载
 *
 * Phase 8 / HULY-03
 *
 * 设计：fail fast — 缺少任何必需 env 立即抛错（不要让 sidecar 起来后再 500）。
 * 返回 immutable 对象（CLAUDE.md immutability 约定）。
 */

import type { BridgeConfig, LogLevel } from './types.js'

/**
 * 必需 env vars 列表（缺一个 sidecar 都不能起）。
 */
const REQUIRED_ENV_VARS = [
  'BRIDGE_TOKEN',
  'HULY_URL',
  'HULY_ACCOUNTS_URL',
  'HULY_WORKSPACE',
  'SERVER_SECRET',
] as const

const VALID_LOG_LEVELS: readonly LogLevel[] = ['debug', 'info', 'warn', 'error']

/**
 * 默认值常量（不要硬编码到逻辑里）。
 */
const DEFAULTS = {
  PORT: 7777,
  BACKEND_URL: 'http://flow-api:8000',
  LOG_LEVEL: 'info' as LogLevel,
  SERVICE_NAME: 'offboarding-bot',
} as const

/**
 * 从 process.env（或注入的 env 对象）解析配置。
 *
 * @param env 默认用 process.env；测试可注入自定义 env
 * @returns 不可变的 BridgeConfig
 * @throws Error 若必需 env 缺失
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): BridgeConfig {
  // 步骤 1：校验所有必需 env 都存在且非空
  const missing: string[] = []
  for (const key of REQUIRED_ENV_VARS) {
    const value = env[key]
    if (value === undefined || value === null || value.trim() === '') {
      missing.push(key)
    }
  }
  if (missing.length > 0) {
    throw new Error(
      `huly-bridge: 缺少必需的环境变量: ${missing.join(', ')} —— 检查 .env 或 docker-compose env 段`,
    )
  }

  // 步骤 2：解析 PORT（可选，默认 7777）
  const portRaw = env.PORT ?? String(DEFAULTS.PORT)
  const port = Number.parseInt(portRaw, 10)
  if (!Number.isFinite(port) || port <= 0 || port > 65535) {
    throw new Error(`huly-bridge: 无效的 PORT 值: "${portRaw}"（必须是 1-65535 的整数）`)
  }

  // 步骤 3：解析 LOG_LEVEL（可选，默认 info）
  const logLevelRaw = (env.LOG_LEVEL ?? DEFAULTS.LOG_LEVEL).toLowerCase()
  if (!VALID_LOG_LEVELS.includes(logLevelRaw as LogLevel)) {
    throw new Error(
      `huly-bridge: 无效的 LOG_LEVEL: "${logLevelRaw}"（合法值: ${VALID_LOG_LEVELS.join(', ')}）`,
    )
  }
  const logLevel = logLevelRaw as LogLevel

  // 步骤 4：组装 immutable config（Object.freeze 防意外 mutation）
  const config: BridgeConfig = Object.freeze({
    port,
    bridgeToken: env.BRIDGE_TOKEN!,
    hulyUrl: env.HULY_URL!,
    hulyAccountsUrl: env.HULY_ACCOUNTS_URL!,
    hulyWorkspace: env.HULY_WORKSPACE!,
    serverSecret: env.SERVER_SECRET!,
    backendUrl: env.BACKEND_URL ?? DEFAULTS.BACKEND_URL,
    logLevel,
    serviceName: env.SERVICE_NAME ?? DEFAULTS.SERVICE_NAME,
  })

  return config
}

/**
 * 输出可见的（脱敏后的）配置摘要，用于启动日志。
 *
 * 敏感字段（BRIDGE_TOKEN / SERVER_SECRET）一律 mask 成 "***"。
 */
export function summarizeConfig(config: BridgeConfig): Record<string, unknown> {
  return {
    port: config.port,
    hulyUrl: config.hulyUrl,
    hulyAccountsUrl: config.hulyAccountsUrl,
    hulyWorkspace: config.hulyWorkspace,
    backendUrl: config.backendUrl,
    logLevel: config.logLevel,
    serviceName: config.serviceName,
    bridgeToken: '***',
    serverSecret: '***',
  }
}
