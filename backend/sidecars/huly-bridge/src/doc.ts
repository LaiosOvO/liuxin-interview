/**
 * huly-bridge sidecar — Doc 业务路由（Teamspace / Document 生命周期）
 *
 * Phase 8 / HULY-05
 *
 * 提供 5 个 HTTP 路由：
 * - POST   /api/doc/create_space     — 创建 Teamspace（PRD §16：离职 · {username}）
 * - POST   /api/doc/create_doc       — 创建 Document（支持 parent）
 * - GET    /api/doc/list_in_space    — 列出某 space 下所有 Document
 * - DELETE /api/doc/document         — 删除单篇 Document
 * - DELETE /api/doc/space            — 删除整个 Teamspace（连带所有文档）
 *
 * 关于 @hcengineering/document：
 * - Plan 04 deviation #1：npm 公网只有 0.7.0，v0.7.423 不可用
 * - 解决方案：使用本地 `@hcengineering/document` shim 声明的 class id；
 *   运行时通过 lookup 模式从 chunter / document 模块取值（如真上线后再 publish）
 * - 兜底：若 document 模块未提供，fallback 用 chunter.Card（暂不实现，留 Plan 06 联调）
 *
 * 设计参考（~/ai/ref/agent/huly-mcp/src/huly/operations/documents.ts 的 mental model）：
 * - Teamspace 是 Space 子类型，含 owners / members；属于 core.space.Space 层级
 * - Document 用 attachedTo: parent_id（无 parent 时用 document.ids.NoParent / 字符串 ""）
 */

import coreModule from '@hcengineering/core'
import documentModule from '@hcengineering/document'
import type { Express, Request, Response } from 'express'

import type { PlatformClient } from '@hcengineering/api-client'

import { resolveAccountByUsername } from './im.js'
import type {
  CreateDocRequest,
  CreateDocResult,
  CreateSpaceRequest,
  CreateSpaceResult,
  ErrorResponse,
  ListInSpaceResult,
  SuccessResponse,
} from './types.js'

/**
 * Plan 04 已采用的 lookup helper —— 兼容 CJS/ESM interop。
 */
function lookup<T>(mod: unknown, path: readonly string[]): T | undefined {
  let cur: unknown = mod
  for (const key of path) {
    if (cur === undefined || cur === null) return undefined
    cur = (cur as Record<string, unknown>)[key]
  }
  return cur as T
}

function getDocumentClass(name: 'Teamspace' | 'Document'): unknown {
  return (
    lookup(documentModule, ['class', name]) ??
    lookup(documentModule, ['default', 'class', name])
  )
}

function getCoreSpaceSpace(): unknown {
  return (
    lookup(coreModule, ['space', 'Space']) ??
    lookup(coreModule, ['default', 'space', 'Space'])
  )
}

function generateId(): string {
  const fn =
    lookup<() => string>(coreModule, ['generateId']) ??
    lookup<() => string>(coreModule, ['default', 'generateId'])
  if (typeof fn === 'function') return fn()
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 14)
}

function errorBody(error: string, code: string): ErrorResponse {
  return { ok: false, error, code }
}

/**
 * 根据 Huly base URL + workspace + doc id 拼接前端可访问 URL。
 *
 * 形如：http://192.168.2.44:8087/workbench/laios/document/{doc_id}
 */
function buildDocUrl(baseUrl: string, workspace: string, docId: string): string {
  const trimmed = baseUrl.replace(/\/$/, '')
  return `${trimmed}/workbench/${workspace}/document/${docId}`
}

function validateCreateSpace(body: unknown): CreateSpaceRequest | string {
  if (typeof body !== 'object' || body === null) return '请求体必须是 JSON 对象'
  const b = body as Partial<CreateSpaceRequest>
  if (typeof b.name !== 'string' || b.name.trim() === '') return '缺少 name 字段'
  if (typeof b.owner_username !== 'string' || b.owner_username.trim() === '') {
    return '缺少 owner_username 字段'
  }
  return { name: b.name.trim(), owner_username: b.owner_username.trim() }
}

function validateCreateDoc(body: unknown): CreateDocRequest | string {
  if (typeof body !== 'object' || body === null) return '请求体必须是 JSON 对象'
  const b = body as Partial<CreateDocRequest>
  if (typeof b.space_id !== 'string' || b.space_id.trim() === '') return '缺少 space_id 字段'
  if (typeof b.title !== 'string' || b.title.trim() === '') return '缺少 title 字段'
  if (typeof b.markdown !== 'string') return '缺少 markdown 字段'
  const parent_id = typeof b.parent_id === 'string' && b.parent_id !== '' ? b.parent_id : undefined
  return {
    space_id: b.space_id.trim(),
    title: b.title.trim(),
    markdown: b.markdown,
    parent_id,
  }
}

/**
 * mountDocRoutes — Express 上挂 5 个 doc 路由。
 *
 * @param app Express 实例
 * @param client PlatformClient
 * @param botAccount bot AccountUuid（作为 Teamspace.members 的 bot 一员）
 * @param hulyBaseUrl Huly Web UI base URL（用于构造 doc URL）
 * @param workspace Huly workspace 名（如 "laios"）
 */
export function mountDocRoutes(
  app: Express,
  client: PlatformClient,
  botAccount: string,
  hulyBaseUrl: string,
  workspace: string,
): void {
  // ============================================================================
  // POST /api/doc/create_space
  // ============================================================================
  app.post('/api/doc/create_space', async (req: Request, res: Response): Promise<void> => {
    const validated = validateCreateSpace(req.body)
    if (typeof validated === 'string') {
      res.status(400).json(errorBody(validated, 'BAD_REQUEST'))
      return
    }
    const { name, owner_username } = validated

    try {
      const ownerAccount = await resolveAccountByUsername(client, owner_username)
      if (ownerAccount === null) {
        res
          .status(404)
          .json(errorBody(`未找到 owner_username=${owner_username} 对应的账号`, 'USER_NOT_FOUND'))
        return
      }

      const teamspaceClass = getDocumentClass('Teamspace')
      const coreSpace = getCoreSpaceSpace()
      if (teamspaceClass === undefined || coreSpace === undefined) {
        throw new Error('document.class.Teamspace 或 core.space.Space 未导出')
      }

      const spaceId = await client.createDoc(teamspaceClass, coreSpace, {
        name,
        description: '离职归档',
        private: false,
        archived: false,
        members: [botAccount, ownerAccount],
        owners: [ownerAccount],
        autoJoin: false,
        type: 'document:ids:DocumentType',
      })

      const data: CreateSpaceResult = { space_id: spaceId }
      res.status(200).json({ ok: true, data } satisfies SuccessResponse<CreateSpaceResult>)
    } catch (err) {
      console.error('[huly-bridge:doc] create_space 失败:', err)
      const message = err instanceof Error ? err.message : 'create_space 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })

  // ============================================================================
  // POST /api/doc/create_doc
  // ============================================================================
  app.post('/api/doc/create_doc', async (req: Request, res: Response): Promise<void> => {
    const validated = validateCreateDoc(req.body)
    if (typeof validated === 'string') {
      res.status(400).json(errorBody(validated, 'BAD_REQUEST'))
      return
    }
    const { space_id, title, markdown, parent_id } = validated

    try {
      const docClass = getDocumentClass('Document')
      if (docClass === undefined) {
        throw new Error('document.class.Document 未导出')
      }

      const docId = generateId()
      await client.createDoc(
        docClass,
        space_id,
        {
          title,
          content: markdown,
          parent: parent_id ?? 'document:ids:NoParent',
          rank: String(Date.now()),
        },
        docId,
      )

      const url = buildDocUrl(hulyBaseUrl, workspace, docId)
      const data: CreateDocResult = { doc_id: docId, url, title }
      res.status(200).json({ ok: true, data } satisfies SuccessResponse<CreateDocResult>)
    } catch (err) {
      console.error('[huly-bridge:doc] create_doc 失败:', err)
      const message = err instanceof Error ? err.message : 'create_doc 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })

  // ============================================================================
  // GET /api/doc/list_in_space
  // ============================================================================
  app.get('/api/doc/list_in_space', async (req: Request, res: Response): Promise<void> => {
    const spaceId = req.query.space_id
    if (typeof spaceId !== 'string' || spaceId.trim() === '') {
      res.status(400).json(errorBody('缺少 space_id 查询参数', 'BAD_REQUEST'))
      return
    }

    try {
      const docClass = getDocumentClass('Document')
      if (docClass === undefined) {
        throw new Error('document.class.Document 未导出')
      }

      const docs = (await client.findAll(docClass, { space: spaceId })) as Array<{
        _id: string
        title: string
      }>

      const data: ListInSpaceResult = {
        docs: docs.map((d) => ({
          id: d._id,
          title: d.title,
          url: buildDocUrl(hulyBaseUrl, workspace, d._id),
        })),
      }
      res.status(200).json({ ok: true, data } satisfies SuccessResponse<ListInSpaceResult>)
    } catch (err) {
      console.error('[huly-bridge:doc] list_in_space 失败:', err)
      const message = err instanceof Error ? err.message : 'list_in_space 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })

  // ============================================================================
  // DELETE /api/doc/document
  // ============================================================================
  app.delete('/api/doc/document', async (req: Request, res: Response): Promise<void> => {
    const docId = req.query.id
    if (typeof docId !== 'string' || docId.trim() === '') {
      res.status(400).json(errorBody('缺少 id 查询参数', 'BAD_REQUEST'))
      return
    }

    try {
      const docClass = getDocumentClass('Document')
      if (docClass === undefined) {
        throw new Error('document.class.Document 未导出')
      }

      const existing = (await client.findOne(docClass, { _id: docId })) as
        | { _id: string; space: string }
        | undefined
      if (existing === undefined || existing === null) {
        // 幂等：不存在视为成功
        res.status(200).json({ ok: true, data: { deleted: false, reason: 'not_found' } })
        return
      }

      await client.removeDoc(docClass, existing.space, existing)
      res.status(200).json({ ok: true, data: { deleted: true } })
    } catch (err) {
      console.error('[huly-bridge:doc] delete document 失败:', err)
      const message = err instanceof Error ? err.message : 'delete_document 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })

  // ============================================================================
  // DELETE /api/doc/space
  // ============================================================================
  app.delete('/api/doc/space', async (req: Request, res: Response): Promise<void> => {
    const spaceId = req.query.id
    if (typeof spaceId !== 'string' || spaceId.trim() === '') {
      res.status(400).json(errorBody('缺少 id 查询参数', 'BAD_REQUEST'))
      return
    }

    try {
      const docClass = getDocumentClass('Document')
      const teamspaceClass = getDocumentClass('Teamspace')
      const coreSpace = getCoreSpaceSpace()
      if (docClass === undefined || teamspaceClass === undefined || coreSpace === undefined) {
        throw new Error('document.class 或 core.space.Space 未导出')
      }

      // Step 1: 列出 space 下所有 Document，逐个 remove
      const docs = (await client.findAll(docClass, { space: spaceId })) as Array<{
        _id: string
        space: string
      }>
      console.warn(
        `[huly-bridge:doc] 即将删除 Teamspace ${spaceId}（含 ${docs.length} 篇文档）`,
      )
      for (const d of docs) {
        await client.removeDoc(docClass, spaceId, d)
      }

      // Step 2: 删 Teamspace 本身
      const space = (await client.findOne(teamspaceClass, { _id: spaceId })) as
        | { _id: string }
        | undefined
      if (space !== undefined && space !== null) {
        await client.removeDoc(teamspaceClass, coreSpace, space)
      }

      res.status(200).json({
        ok: true,
        data: { deleted: true, documents_removed: docs.length },
      })
    } catch (err) {
      console.error('[huly-bridge:doc] delete space 失败:', err)
      const message = err instanceof Error ? err.message : 'delete_space 内部错误'
      res.status(500).json(errorBody(message, 'INTERNAL_ERROR'))
    }
  })
}
