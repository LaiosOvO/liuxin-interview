/**
 * @hcengineering/* 包类型 shim
 *
 * Phase 8 / HULY-03
 *
 * 背景：v0.7.423 npm publish 没附带完整 .d.ts（核心 SDK 仅含 .js）。
 * 我们只声明用到的接口子集（不追求完整类型）— sidecar 业务功能
 * 通过 vitest mock + 真实集成测试（Plan 05）保证正确性。
 *
 * 这是临时方案；上游 huly 团队后续补 .d.ts 后本文件可删。
 */

// CJS interop: 源码 default import 后 lazy lookup default + 顶级（兼容 vitest mock 和真实运行时）
// 故 shim 同时声明 default export + 命名 export

declare module '@hcengineering/core' {
  export type AccountUuid = string
  export const systemAccountUuid: AccountUuid

  const core: {
    systemAccountUuid: AccountUuid
    [key: string]: unknown
  }
  export default core
}

declare module '@hcengineering/platform' {
  export function setMetadata<T>(key: unknown, value: T): void
  export function getMetadata<T>(key: unknown): T | undefined

  const platform: {
    setMetadata: typeof setMetadata
    getMetadata: typeof getMetadata
    [key: string]: unknown
  }
  export default platform
}

declare module '@hcengineering/server-token' {
  export interface ServiceExtra {
    service?: string
    admin?: 'true'
    [key: string]: unknown
  }

  export function generateToken(
    accountUuid: string,
    workspaceUuid?: string | undefined,
    extra?: ServiceExtra,
  ): string

  export function decodeToken(token: string): unknown

  const serverToken: {
    metadata: {
      Secret: unknown
      Service: unknown
    }
    generateToken: typeof generateToken
    decodeToken: typeof decodeToken
  }
  export default serverToken
}

declare module '@hcengineering/server-client' {
  const serverClient: {
    metadata: {
      Endpoint: unknown
      UserAgent: unknown
    }
  }
  export default serverClient
}

declare module '@hcengineering/api-client' {
  export interface ConnectOptions {
    token: string
    workspace: string
    socketFactory?: unknown
    connectionTimeout?: number
  }

  export interface PlatformClient {
    findAll: (...args: unknown[]) => Promise<unknown[]>
    findOne: (...args: unknown[]) => Promise<unknown>
    createDoc: (...args: unknown[]) => Promise<string>
    updateDoc: (...args: unknown[]) => Promise<unknown>
    removeDoc: (...args: unknown[]) => Promise<unknown>
    addCollection: (...args: unknown[]) => Promise<unknown>
    close: () => Promise<void>
  }

  export function connect(url: string, options: ConnectOptions): Promise<PlatformClient>

  const apiClient: {
    connect: typeof connect
    [key: string]: unknown
  }
  export default apiClient
}

declare module '@hcengineering/chunter' {
  /** Chunter 模块 class id 集合 */
  export interface ChunterClass {
    DirectMessage: unknown
    Channel: unknown
    ChatMessage: unknown
  }

  const chunter: {
    class: ChunterClass
    [key: string]: unknown
  }
  export default chunter
}

declare module '@hcengineering/contact' {
  export interface ContactClass {
    SocialIdentity: unknown
    Person: unknown
  }

  export interface ContactMixin {
    Employee: unknown
  }

  const contact: {
    class: ContactClass
    mixin: ContactMixin
    [key: string]: unknown
  }
  export default contact
}

// Document 包 v0.7.423 在 npm 公网不可用（Plan 04 deviation #1）；本 shim 仅声明
// 类型契约让 sidecar 编译通过；运行时 Plan 05 Task 2 doc.ts 用 chunter.Card 兜底
declare module '@hcengineering/document' {
  export interface DocumentClass {
    Teamspace: unknown
    Document: unknown
  }
  const document: {
    class: DocumentClass
    [key: string]: unknown
  }
  export default document
}

// account-client 是 server-client 间接依赖（不显式 in package.json，
// 但 node_modules 已 hoist 安装）；Plan 06 admin API 用 getClient() 拿真人 admin token。
// 仅声明用到的方法签名，其它字段任意。
declare module '@hcengineering/account-client' {
  export interface LoginInfo {
    readonly account: string
    readonly token: string
    readonly name?: string
  }

  export interface WorkspaceLoginInfo extends LoginInfo {
    readonly workspace: string
    readonly workspaceUrl: string
    readonly workspaceDataId?: string
    readonly endpoint: string
  }

  export interface AccountClient {
    login(email: string, password: string): Promise<LoginInfo>
    signUp(email: string, password: string, first: string, last: string): Promise<LoginInfo>
    signUpJoin(
      email: string,
      password: string,
      first: string,
      last: string,
      inviteId: string,
      workspaceUrl: string,
    ): Promise<WorkspaceLoginInfo>
    selectWorkspace(workspaceUrl: string, kind?: string): Promise<WorkspaceLoginInfo>
    createInvite(exp: number, emailMask: string, limit: number, role: string): Promise<string>
    createWorkspace(name: string, region?: string): Promise<WorkspaceLoginInfo>
    getLoginInfoByToken?: () => Promise<unknown>
  }

  export function getClient(
    accountsUrl?: string,
    token?: string,
    retryTimeoutMs?: number,
  ): AccountClient

  const accountClient: {
    getClient: typeof getClient
    [key: string]: unknown
  }
  export default accountClient
}
