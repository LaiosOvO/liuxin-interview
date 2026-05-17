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

declare module '@hcengineering/chunter'
declare module '@hcengineering/contact'
