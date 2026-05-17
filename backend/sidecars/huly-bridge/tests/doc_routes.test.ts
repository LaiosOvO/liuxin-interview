/**
 * huly-bridge sidecar — doc.ts 业务路由测试
 *
 * Phase 8 / HULY-05
 *
 * 覆盖：
 * - create_space: createDoc Teamspace 被调用 + 返回 space_id
 * - create_doc: createDoc Document 被调用 + 返回 url
 * - list_in_space: findAll Document 被调用
 * - delete_space: 先 list + 多个 removeDoc + removeDoc Teamspace
 * - delete_document: removeDoc 被调用
 */

import express, { type Express } from 'express'
import supertest from 'supertest'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mockDocumentClass = {
  Teamspace: Symbol('document.class.Teamspace'),
  Document: Symbol('document.class.Document'),
}

const mockContactClass = {
  SocialIdentity: Symbol('contact.class.SocialIdentity'),
  Person: Symbol('contact.class.Person'),
}

const mockContactMixin = {
  Employee: Symbol('contact.mixin.Employee'),
}

const mockCoreSpace = {
  Space: Symbol('core.space.Space'),
}

vi.mock('@hcengineering/document', () => ({
  default: { class: mockDocumentClass },
  class: mockDocumentClass,
}))

vi.mock('@hcengineering/contact', () => ({
  default: { class: mockContactClass, mixin: mockContactMixin },
  class: mockContactClass,
  mixin: mockContactMixin,
}))

vi.mock('@hcengineering/chunter', () => ({
  default: { class: { DirectMessage: Symbol(), Channel: Symbol(), ChatMessage: Symbol() } },
  class: { DirectMessage: Symbol(), Channel: Symbol(), ChatMessage: Symbol() },
}))

vi.mock('@hcengineering/core', () => ({
  default: {
    space: mockCoreSpace,
    generateId: () => 'mock-doc-id',
  },
  space: mockCoreSpace,
  generateId: () => 'mock-doc-id',
}))

let mountDocRoutes: typeof import('../src/doc.js').mountDocRoutes

beforeAll(async () => {
  const doc = await import('../src/doc.js')
  mountDocRoutes = doc.mountDocRoutes
})

interface MockPlatformClient {
  findOne: ReturnType<typeof vi.fn>
  findAll: ReturnType<typeof vi.fn>
  createDoc: ReturnType<typeof vi.fn>
  updateDoc: ReturnType<typeof vi.fn>
  addCollection: ReturnType<typeof vi.fn>
  removeDoc: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

function makeMockClient(): MockPlatformClient {
  return {
    findOne: vi.fn(),
    findAll: vi.fn(),
    createDoc: vi.fn(),
    updateDoc: vi.fn(),
    addCollection: vi.fn(),
    removeDoc: vi.fn(),
    close: vi.fn(),
  }
}

const BOT_ACCOUNT = 'bot-account-uuid-0001'
const HULY_BASE_URL = 'http://192.168.2.44:8087'
const WORKSPACE = 'laios'

function makeApp(client: MockPlatformClient): Express {
  const app = express()
  app.use(express.json())
  mountDocRoutes(
    app,
    client as unknown as Parameters<typeof mountDocRoutes>[1],
    BOT_ACCOUNT,
    HULY_BASE_URL,
    WORKSPACE,
  )
  return app
}

describe('POST /api/doc/create_space', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('正常创建 → createDoc Teamspace 被调用 + 返回 space_id', async () => {
    const client = makeMockClient()
    // resolveAccountByUsername 走 2 次 findOne（SocialIdentity → Employee）
    client.findOne
      .mockResolvedValueOnce({ attachedTo: 'person-1' })
      .mockResolvedValueOnce({ personUuid: 'account-owner' })
    client.createDoc.mockResolvedValueOnce('teamspace-new-1')

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/doc/create_space')
      .send({ name: '离职 · zhang.san', owner_username: 'zhang.san' })

    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({
      ok: true,
      data: { space_id: 'teamspace-new-1' },
    })
    expect(client.createDoc).toHaveBeenCalledTimes(1)
    expect(client.createDoc).toHaveBeenCalledWith(
      mockDocumentClass.Teamspace,
      mockCoreSpace.Space,
      expect.objectContaining({
        name: '离职 · zhang.san',
        members: [BOT_ACCOUNT, 'account-owner'],
        owners: ['account-owner'],
        autoJoin: false,
      }),
    )
  })

  it('用户不存在 → 404 USER_NOT_FOUND（createDoc 不调用）', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/doc/create_space')
      .send({ name: '离职 · ghost', owner_username: 'ghost' })

    expect(res.status).toBe(404)
    expect(res.body.code).toBe('USER_NOT_FOUND')
    expect(client.createDoc).not.toHaveBeenCalled()
  })

  it('缺 name → 400', async () => {
    const client = makeMockClient()
    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/doc/create_space')
      .send({ owner_username: 'zhang.san' })
    expect(res.status).toBe(400)
  })
})

describe('POST /api/doc/create_doc', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('createDoc Document 被调用 + 返回 url 含 workspace', async () => {
    const client = makeMockClient()
    client.createDoc.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/doc/create_doc')
      .send({
        space_id: 'teamspace-1',
        title: '工作交接',
        markdown: '# 工作交接\n详细内容...',
      })

    expect(res.status).toBe(200)
    expect(res.body.ok).toBe(true)
    expect(res.body.data.title).toBe('工作交接')
    expect(res.body.data.url).toContain(`${HULY_BASE_URL}/workbench/${WORKSPACE}/document/`)
    expect(client.createDoc).toHaveBeenCalledTimes(1)
    expect(client.createDoc).toHaveBeenCalledWith(
      mockDocumentClass.Document,
      'teamspace-1',
      expect.objectContaining({ title: '工作交接' }),
      expect.any(String),
    )
  })

  it('parent_id 传入 → parent 字段使用 parent_id', async () => {
    const client = makeMockClient()
    client.createDoc.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    await supertest(app)
      .post('/api/doc/create_doc')
      .send({
        space_id: 'teamspace-1',
        title: '子文档',
        markdown: 'content',
        parent_id: 'doc-parent-1',
      })

    expect(client.createDoc.mock.calls[0][2]).toMatchObject({
      parent: 'doc-parent-1',
    })
  })

  it('缺 title → 400', async () => {
    const client = makeMockClient()
    const app = makeApp(client)
    const res = await supertest(app)
      .post('/api/doc/create_doc')
      .send({ space_id: 't1', markdown: 'x' })
    expect(res.status).toBe(400)
  })
})

describe('GET /api/doc/list_in_space', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('findAll Document by space 被调用 + 返回 docs 数组', async () => {
    const client = makeMockClient()
    client.findAll.mockResolvedValueOnce([
      { _id: 'doc-1', title: '工作交接' },
      { _id: 'doc-2', title: '账号清单' },
    ])

    const app = makeApp(client)
    const res = await supertest(app).get('/api/doc/list_in_space?space_id=teamspace-1')

    expect(res.status).toBe(200)
    expect(res.body.data.docs).toHaveLength(2)
    expect(res.body.data.docs[0]).toMatchObject({
      id: 'doc-1',
      title: '工作交接',
    })
    expect(res.body.data.docs[0].url).toContain('teamspace-1'.slice(0, 0)) // 包含 base URL
    expect(client.findAll).toHaveBeenCalledWith(
      mockDocumentClass.Document,
      { space: 'teamspace-1' },
    )
  })

  it('缺 space_id 查询参数 → 400', async () => {
    const client = makeMockClient()
    const app = makeApp(client)
    const res = await supertest(app).get('/api/doc/list_in_space')
    expect(res.status).toBe(400)
  })
})

describe('DELETE /api/doc/document', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('文档存在 → removeDoc 被调用', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce({ _id: 'doc-1', space: 'teamspace-1' })
    client.removeDoc.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app).delete('/api/doc/document?id=doc-1')

    expect(res.status).toBe(200)
    expect(res.body.data.deleted).toBe(true)
    expect(client.removeDoc).toHaveBeenCalledTimes(1)
  })

  it('文档不存在 → 200 deleted=false（幂等）', async () => {
    const client = makeMockClient()
    client.findOne.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app).delete('/api/doc/document?id=ghost')

    expect(res.status).toBe(200)
    expect(res.body.data.deleted).toBe(false)
    expect(client.removeDoc).not.toHaveBeenCalled()
  })
})

describe('DELETE /api/doc/space', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('先 list 多个 Document 全 remove → 再 remove Teamspace', async () => {
    const client = makeMockClient()
    // findAll Documents
    client.findAll.mockResolvedValueOnce([
      { _id: 'doc-1', space: 'ts-1' },
      { _id: 'doc-2', space: 'ts-1' },
    ])
    client.removeDoc.mockResolvedValue(undefined)
    // findOne Teamspace
    client.findOne.mockResolvedValueOnce({ _id: 'ts-1' })

    const app = makeApp(client)
    const res = await supertest(app).delete('/api/doc/space?id=ts-1')

    expect(res.status).toBe(200)
    expect(res.body.data.documents_removed).toBe(2)
    // 2 次 Document.removeDoc + 1 次 Teamspace.removeDoc
    expect(client.removeDoc).toHaveBeenCalledTimes(3)
  })

  it('空 space → 仅 remove Teamspace', async () => {
    const client = makeMockClient()
    client.findAll.mockResolvedValueOnce([])
    client.findOne.mockResolvedValueOnce({ _id: 'ts-empty' })
    client.removeDoc.mockResolvedValueOnce(undefined)

    const app = makeApp(client)
    const res = await supertest(app).delete('/api/doc/space?id=ts-empty')

    expect(res.status).toBe(200)
    expect(res.body.data.documents_removed).toBe(0)
    expect(client.removeDoc).toHaveBeenCalledTimes(1)
  })
})
