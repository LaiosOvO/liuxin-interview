/**
 * Vitest 配置 — huly-bridge sidecar
 *
 * 测试不需要真连 Huly；只校验配置解析 / 鉴权中间件 / 路由 stub 行为。
 */

import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: ['tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.ts'],
      exclude: ['src/types.ts'],
    },
    testTimeout: 10_000,
  },
})
