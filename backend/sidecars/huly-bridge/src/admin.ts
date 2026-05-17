/**
 * huly-bridge sidecar — Admin API（Plan 06 / HULY-08）
 *
 * 暴露给 seed 脚本的内部 admin 路由，把业务 DB 用户批量同步到 Huly
 * （账号创建 + workspace 加入）。
 *
 * 安全模型（CLAUDE.md §3.5）：
 * - 第一道：bridgeAuth（X-Bridge-Token）— 同业务路由
 * - 第二道：adminAuth（X-Admin-Token）— 独立 secret，仅注入到 seed 脚本环境
 * - 双 token 同时正确才放行
 *
 * 实现路径（避开 Pitfall #1 — createInviteLink autoJoin 仅 service=schedule 允许）：
 * 1. 用 HULY_ADMIN_EMAIL/PASSWORD 调 accountClient.login → 拿真人 admin token
 * 2. 用 admin token 调 createInvite(emailMask, limit=1)（不传 autoJoin）拿 inviteId
 * 3. 调 signUp(email, password, first, last) 创账号（如已存在，捕 ACCOUNT_ALREADY_EXISTS 兜底幂等）
 * 4. 用 sign-up 返回的 user token 调 signUpJoin(email, password, first, last, inviteId, workspaceUrl)
 *    完成 workspace 加入
 *
 * 幂等：
 * - signUp 抛 ACCOUNT_ALREADY_EXISTS / DUPLICATE → 转 200 {skipped:true, account_uuid: '已存在'}
 * - 重跑同 email + 已加 workspace → 仍 200 skipped（防 seed 脚本重跑炸）
 *
 * 缓存：
 * - admin token 缓存到内存（5 min TTL），避免每次 signup_join 都重新 login
 * - sidecar 重启即失效（无需持久化）
 */

import accountClientModule from '@hcengineering/account-client'
import type { AccountClient } from '@hcengineering/account-client'
import type { Express, Request, Response } from 'express'

import { adminAuth, bridgeAuth } from './middleware.js'
import type {
  BridgeConfig,
  ErrorResponse,
  SignUpJoinRequest,
  SignUpJoinResult,
  SuccessResponse,
} from './types.js'

/**
 * CJS interop helper — 从 default / 顶级 lookup 一个属性（同 im.ts / doc.ts 模式）。
 */
function lookup<T>(mod: unknown, path: readonly string[]): T | undefined {
  let cur: unknown = mod
  for (const key of path) {
    if (cur === undefined || cur === null) return undefined
    cur = (cur as Record<string, unknown>)[key]
  }
  return cur as T
}

/**
 * 解出 account-client getClient 函数（兼 CJS / ESM）。
 */
function getAccountClientFactory(): (
  accountsUrl?: string,
  token?: string,
  retryTimeoutMs?: number,
) => AccountClient {
  const fn =
    lookup<(a?: string, t?: string, r?: number) => AccountClient>(accountClientModule, ['getClient']) ??
    lookup<(a?: string, t?: string, r?: number) => AccountClient>(accountClientModule, [
      'default',
      'getClient',
    ])
  if (typeof fn !== 'function') {
    throw new Error('huly-bridge: @hcengineering/account-client 未导出 getClient — 检查 SDK 版本')
  }
  return fn
}

/**
 * Admin token 缓存（避免每次 signup_join 都重 login）。
 */
interface CachedAdminToken {
  readonly token: string
  readonly account: string
  readonly expiresAt: number
}

let cachedAdmin: CachedAdminToken | null = null

/** TTL: 5 分钟（Huly v0.7 token 自身有效期一般 1h+，本地 cache 短点更安全） */
const ADMIN_TOKEN_TTL_MS = 5 * 60 * 1000

/**
 * 拿（缓存的或新建的）admin AccountClient。
 *
 * 缓存语义：
 * - 同进程内 5 分钟内复用
 * - 过期 / 首次调用 → login(adminEmail, adminPassword) → 缓存
 *
 * 错误：
 * - admin 凭证缺 → 抛 Error
 * - login 失败 → 抛上层错误（路由层 catch 转 400/500）
 */
export async function getAdminClient(config: BridgeConfig): Promise<AccountClient> {
  if (!config.adminEmail || !config.adminPassword) {
    throw new Error(
      'huly-bridge: admin API 需要 HULY_ADMIN_EMAIL + HULY_ADMIN_PASSWORD env',
    )
  }

  const now = Date.now()
  const factory = getAccountClientFactory()

  // 缓存命中
  if (cachedAdmin !== null && cachedAdmin.expiresAt > now) {
    return factory(config.hulyAccountsUrl, cachedAdmin.token)
  }

  // 走 login（先用 anonymous client）
  const anonClient = factory(config.hulyAccountsUrl)
  const loginInfo = await anonClient.login(config.adminEmail, config.adminPassword)

  cachedAdmin = {
    token: loginInfo.token,
    account: loginInfo.account,
    expiresAt: now + ADMIN_TOKEN_TTL_MS,
  }

  return factory(config.hulyAccountsUrl, loginInfo.token)
}

/**
 * 仅 测试 用 — 清缓存。
 *
 * @internal
 */
export function _resetAdminCacheForTests(): void {
  cachedAdmin = null
}

/**
 * 仅 测试 用 — 注入 mock account-client factory（绕开真模块解析）。
 *
 * 为了让 vitest 能精确控制 AccountClient 返回，本 helper 接受一个 factory
 * 函数（与 getClient 同签名），覆盖默认 lookup。
 *
 * @internal
 */
let _testAccountClientFactory:
  | ((accountsUrl?: string, token?: string, retryTimeoutMs?: number) => AccountClient)
  | null = null

export function _setTestAccountClientFactory(
  fn: ((accountsUrl?: string, token?: string, retryTimeoutMs?: number) => AccountClient) | null,
): void {
  _testAccountClientFactory = fn
}

/**
 * 在测试模式下走 _testAccountClientFactory；生产走 lookup。
 */
function getEffectiveFactory(): (
  accountsUrl?: string,
  token?: string,
  retryTimeoutMs?: number,
) => AccountClient {
  if (_testAccountClientFactory !== null) {
    return _testAccountClientFactory
  }
  return getAccountClientFactory()
}

/**
 * 走 effective factory 拿 admin client（测试 + 生产共用入口）。
 */
async function getAdminClientInternal(config: BridgeConfig): Promise<AccountClient> {
  if (!config.adminEmail || !config.adminPassword) {
    throw new Error(
      'huly-bridge: admin API 需要 HULY_ADMIN_EMAIL + HULY_ADMIN_PASSWORD env',
    )
  }

  const now = Date.now()
  const factory = getEffectiveFactory()

  if (cachedAdmin !== null && cachedAdmin.expiresAt > now) {
    return factory(config.hulyAccountsUrl, cachedAdmin.token)
  }

  const anonClient = factory(config.hulyAccountsUrl)
  const loginInfo = await anonClient.login(config.adminEmail, config.adminPassword)

  cachedAdmin = {
    token: loginInfo.token,
    account: loginInfo.account,
    expiresAt: now + ADMIN_TOKEN_TTL_MS,
  }

  return factory(config.hulyAccountsUrl, loginInfo.token)
}

/**
 * 验证 signup_join 请求体。
 */
function validateSignUpJoin(body: unknown): SignUpJoinRequest | string {
  if (typeof body !== 'object' || body === null) return '请求体必须是 JSON 对象'
  const b = body as Partial<SignUpJoinRequest>
  if (typeof b.username !== 'string' || b.username.trim() === '') return '缺少 username'
  if (typeof b.email !== 'string' || b.email.trim() === '') return '缺少 email'
  if (typeof b.password !== 'string' || b.password === '') return '缺少 password'
  if (typeof b.first_name !== 'string') return '缺少 first_name'
  if (typeof b.last_name !== 'string') return '缺少 last_name'
  return {
    username: b.username.trim(),
    email: b.email.trim().toLowerCase(),
    password: b.password,
    first_name: b.first_name,
    last_name: b.last_name,
    role: typeof b.role === 'string' && b.role.trim() !== '' ? b.role.trim() : 'USER',
  }
}

/**
 * 错误响应 helper。
 */
function errorBody(error: string, code: string): ErrorResponse {
  return { ok: false, error, code }
}

/**
 * 错误信息特征 — Huly 返回的 "account already exists" 类错误。
 *
 * 上游错误 code 集合（@hcengineering/account 源码中已观察）：
 * - account-already-exists
 * - duplicate-account
 * - workspace-member-already-exists
 *
 * 任何一个匹配 → 视为幂等成功。
 */
function isAlreadyExistsError(err: unknown): boolean {
  const message =
    err instanceof Error ? err.message.toLowerCase() : String(err).toLowerCase()
  return (
    message.includes('already exists') ||
    message.includes('duplicate') ||
    message.includes('account_already_exists') ||
    message.includes('account-already-exists')
  )
}

/**
 * 核心 handler — POST /api/admin/signup_join。
 *
 * 抽到 export function 便于单测直接调用（避免完整 Express stack 起 listener）。
 */
export async function handleSignUpJoin(
  config: BridgeConfig,
  body: unknown,
): Promise<{ status: number; body: SuccessResponse<SignUpJoinResult> | ErrorResponse }> {
  const validated = validateSignUpJoin(body)
  if (typeof validated === 'string') {
    return { status: 400, body: errorBody(validated, 'BAD_REQUEST') }
  }
  const { email, password, first_name, last_name, role } = validated

  // 拿 admin client（cached）
  let adminClient: AccountClient
  try {
    adminClient = await getAdminClientInternal(config)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'admin login 失败'
    console.error('[huly-bridge:admin] getAdminClient 失败:', err)
    return { status: 500, body: errorBody(message, 'ADMIN_LOGIN_FAILED') }
  }

  // 步骤 1：创建 invite（exp = now + 1 day，limit=1，role）
  const exp = Date.now() + 24 * 60 * 60 * 1000
  let inviteId: string
  try {
    inviteId = await adminClient.createInvite(exp, email, 1, role ?? 'USER')
  } catch (err) {
    // 如果 createInvite 因 workspace 不存在 / admin 无权 → 400 透传
    const message = err instanceof Error ? err.message : 'createInvite 失败'
    console.error('[huly-bridge:admin] createInvite 失败:', err)
    return { status: 400, body: errorBody(message, 'CREATE_INVITE_FAILED') }
  }

  // 步骤 2：signUpJoin —— 一步完成「signUp + 加 workspace」
  // 优先用 signUpJoin（公开 endpoint，不需要 token）：sign up 账号同时立即 join workspace
  const anonFactory = getEffectiveFactory()
  const anonClient = anonFactory(config.hulyAccountsUrl)

  try {
    const result = await anonClient.signUpJoin(
      email,
      password,
      first_name,
      last_name,
      inviteId,
      config.hulyWorkspace,
    )
    const data: SignUpJoinResult = {
      account_uuid: result.account,
      skipped: false,
    }
    return { status: 200, body: { ok: true, data } satisfies SuccessResponse<SignUpJoinResult> }
  } catch (err) {
    if (isAlreadyExistsError(err)) {
      // 兜底幂等：账号已存在 → 走 login 拿 accountUuid 后返回 skipped
      try {
        const loginInfo = await anonClient.login(email, password)
        const data: SignUpJoinResult = {
          account_uuid: loginInfo.account,
          skipped: true,
        }
        return { status: 200, body: { ok: true, data } satisfies SuccessResponse<SignUpJoinResult> }
      } catch (loginErr) {
        // login 也失败 → 账号存在但密码不一致；这种 case 应人工干预
        const lm = loginErr instanceof Error ? loginErr.message : String(loginErr)
        console.warn(
          '[huly-bridge:admin] account 已存在但 login 失败（密码不一致？）:',
          lm,
        )
        return {
          status: 409,
          body: errorBody(
            `账号 ${email} 已存在但 login 失败（密码可能不一致）: ${lm}`,
            'ACCOUNT_EXISTS_PASSWORD_MISMATCH',
          ),
        }
      }
    }

    const message = err instanceof Error ? err.message : 'signUpJoin 失败'
    console.error('[huly-bridge:admin] signUpJoin 失败:', err)
    return { status: 400, body: errorBody(message, 'SIGNUP_JOIN_FAILED') }
  }
}

/**
 * 在 Express app 上挂 Admin 业务路由。
 *
 * 路径：POST /api/admin/signup_join
 * 鉴权链：bridgeAuth (X-Bridge-Token) → adminAuth (X-Admin-Token) → handler
 *
 * 注意：本函数 mount 在主 app 已有 bridgeAuth 之后 — 仅再叠一层 adminAuth
 * （不需要重复 bridgeAuth，主 app 已包）。
 *
 * @param app Express 实例（已 mount bridgeAuth）
 * @param config BridgeConfig（含 adminToken / adminEmail / adminPassword）
 */
export function mountAdminRoutes(app: Express, config: BridgeConfig): void {
  if (!config.adminToken) {
    console.warn(
      '[huly-bridge:admin] ADMIN_TOKEN 未配置 — admin 路由不挂载（生产场景纯业务 OK；seed 场景需配 ADMIN_TOKEN）',
    )
    return
  }

  const adminMw = adminAuth(config.adminToken)

  app.post('/api/admin/signup_join', adminMw, async (req: Request, res: Response): Promise<void> => {
    const result = await handleSignUpJoin(config, req.body)
    res.status(result.status).json(result.body)
  })

  console.log(
    '[huly-bridge:admin] 已 mount admin API（双重鉴权 BRIDGE_TOKEN + ADMIN_TOKEN）：POST /api/admin/signup_join',
  )
}

export { bridgeAuth }
