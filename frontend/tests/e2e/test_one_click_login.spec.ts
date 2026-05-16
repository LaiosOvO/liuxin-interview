/**
 * E2E：一键登录入口冒烟测试（WEB-02）
 *
 * 当前 Phase 5 只占位：验证页面能加载 + 在无 token 时显示错误提示。
 * 完整 flow（带真实 token 拿后端 cookie 跳转）等 Phase 6 部署后联调。
 *
 * 跑法（需先启动 frontend dev server）：
 *   pnpm dev &
 *   pnpm test:e2e
 *
 * 若 CI / 本地无 dev server → 测试会 timeout，可用 test.skip() 跳过。
 */
import { test, expect } from '@playwright/test';

const SKIP_REASON_NO_SERVER = 'E2E_BASE_URL 不可达 — 请先 pnpm dev 启 frontend';

async function isServerUp(baseURL: string): Promise<boolean> {
  try {
    const resp = await fetch(baseURL, { signal: AbortSignal.timeout(2000) });
    return resp.ok || resp.status < 500;
  } catch {
    return false;
  }
}

test.describe('一键登录入口 /flow/handle', () => {
  test.beforeAll(async ({}, testInfo) => {
    const baseURL = testInfo.project.use.baseURL ?? 'http://localhost:3000';
    const up = await isServerUp(baseURL);
    if (!up) {
      test.skip(true, SKIP_REASON_NO_SERVER);
    }
  });

  test('无 token 时显示鉴权失败提示', async ({ page }) => {
    await page.goto('/flow/handle/');
    await expect(page.getByText('鉴权失败', { exact: false })).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByText('链接缺少 token 参数', { exact: false })).toBeVisible();
  });

  test('伪 token 时展示后端 error envelope 内容', async ({ page }) => {
    await page.goto('/flow/handle/?token=fake-token-that-cannot-decode-1234567890');
    // 后端会返回 401 + envelope { error: "..." }，前端展示
    await expect(page.getByText('鉴权失败', { exact: false })).toBeVisible({
      timeout: 10000,
    });
  });

  test('首页根据无 session 显示登录提示', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('离职流程系统')).toBeVisible();
    await expect(
      page.getByText('请通过邮件 / Mattermost', { exact: false })
    ).toBeVisible();
  });
});
