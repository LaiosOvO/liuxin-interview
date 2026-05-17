/**
 * E2E: Huly UI 起离职流程（Phase 8 / HULY-08 验收）
 *
 * 测试目标：模拟 it.charlie 登录 Huly UI → 找到 offboarding-bot DM → 发"我要离职"
 * → 等 bot 回复 → 验证业务 DB flow_instances 表新行
 *
 * 前置（必须先准备好）：
 *   1. Huly stack 14 容器 + huly-bridge sidecar + offboarding-backend 全部启动
 *      docker compose --profile huly-stack up -d
 *      docker compose --profile huly up -d huly-bridge
 *      docker compose up -d backend
 *   2. seed 完成：scripts/seed_demo_data.py + scripts/seed_huly_users.py
 *   3. .env 切 IM_PROVIDER=huly + 重启 backend
 *   4. 设 env：
 *      HULY_URL=http://192.168.2.44:8087
 *      HULY_USER_PASSWORD=<from .env>
 *      BACKEND_URL=http://192.168.2.44:8000
 *
 * 跑法：
 *   cd frontend
 *   HULY_URL=http://192.168.2.44:8087 \
 *     HULY_USER_PASSWORD=<pwd> \
 *     BACKEND_URL=http://192.168.2.44:8000 \
 *     npx playwright test tests/e2e/huly_im_flow.spec.ts --headed --reporter=list
 *
 * 截图输出到 docs/screenshots/huly-flow-*.png
 *
 * 注意：本 spec 用 `test.skip()` 在无 Huly 环境时自动跳过，CI 通过。
 *      实际验收时手动启 Huly 后跑。
 */

import { expect, test } from '@playwright/test'

const HULY_URL = process.env.HULY_URL ?? 'http://192.168.2.44:8087'
const HULY_USER_PASSWORD = process.env.HULY_USER_PASSWORD ?? ''
const BACKEND_URL = process.env.BACKEND_URL ?? 'http://192.168.2.44:8000'
const SCREENSHOT_DIR = '../docs/screenshots'

/**
 * 检测 Huly UI 是否可达 — 不可达则 skip 整组测试。
 */
async function isHulyUp(): Promise<boolean> {
  try {
    const resp = await fetch(HULY_URL, { signal: AbortSignal.timeout(3000) })
    return resp.status < 500
  } catch {
    return false
  }
}

test.describe('Huly IM 流程 — it.charlie 起离职', () => {
  test.beforeAll(async () => {
    if (!HULY_USER_PASSWORD) {
      test.skip(true, 'HULY_USER_PASSWORD env 未设；请从 .env 注入后重跑')
    }
    const up = await isHulyUp()
    if (!up) {
      test.skip(
        true,
        `Huly UI 不可达 (${HULY_URL})；启 huly-stack 后重跑：` +
          'docker compose --profile huly-stack up -d',
      )
    }
  })

  test('it.charlie 在 Huly DM 发"我要离职" → 流程启动 → bot 回复 + DB 写入', async ({
    page,
  }) => {
    // === Step 1: 打开 Huly 登录页 ===
    await page.goto(HULY_URL)
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/huly-flow-1-login.png`,
      fullPage: true,
    })

    // === Step 2: 用 it.charlie 登录 ===
    // 注：实际 selector 需在 Huly v0.7.423 UI 上 codegen 后调整
    // 这里用最 generic 的 selector；首次跑时可能要 npx playwright codegen 探测
    await page.fill('input[name="email"], input[type="email"]', 'it.charlie@demo.local')
    await page.fill('input[name="password"], input[type="password"]', HULY_USER_PASSWORD)
    await page.click('button[type="submit"]')

    // 等待登录后主界面（chunter 频道列表或类似元素）
    await page.waitForLoadState('networkidle', { timeout: 15000 })
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/huly-flow-2-loggedin.png`,
      fullPage: true,
    })

    // === Step 3: 找到 offboarding-bot DM ===
    // Huly UI 的 DM 入口：左侧 sidebar → Direct Messages
    // 实际 selector 需要根据 v0.7.423 UI 调整
    const botDmLink = page.locator('text=offboarding-bot').first()
    await botDmLink.waitFor({ timeout: 10000 })
    await botDmLink.click()
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/huly-flow-3-dm-opened.png`,
      fullPage: true,
    })

    // === Step 4: 发送"我要离职" ===
    // Huly chat input — Tiptap editor，需要 contenteditable
    const chatInput = page.locator('[contenteditable="true"]').first()
    await chatInput.waitFor({ timeout: 5000 })
    await chatInput.fill('我要离职')
    await page.keyboard.press('Enter')

    // === Step 5: 等 bot 回复 ===
    // sidecar 2s poll + dispatch + post 总耗时 < 10s
    const replyLocator = page.locator('text=/流程已启动|您的离职流程已创建|已为您创建/i').first()
    await expect(replyLocator).toBeVisible({ timeout: 15000 })
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/huly-flow-4-bot-reply.png`,
      fullPage: true,
    })

    // === Step 6: 验证业务 DB（通过 backend HTTP API） ===
    const flowResp = await page.request.get(
      `${BACKEND_URL}/api/flows?employee_id=it.charlie`,
    )
    expect(flowResp.status()).toBe(200)
    const flowBody = await flowResp.json()
    const flows = flowBody.data ?? flowBody
    expect(Array.isArray(flows) ? flows.length : 0).toBeGreaterThanOrEqual(1)

    const latest = Array.isArray(flows) ? flows[0] : null
    expect(latest?.status).toBe('in_progress')
  })
})
