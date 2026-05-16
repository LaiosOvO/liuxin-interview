/**
 * Next.js 15 配置 — 静态导出
 *
 * 关键决策（Phase 5）：
 * - output: 'export' → 输出到 out/，nginx 直接 serve（不跑 Node 运行时）
 * - trailingSlash: true → nginx try_files 友好（/foo/ → /foo/index.html）
 * - 全页面 'use client' → 静态导出限制，禁用 SSR / Server Actions
 * - 动态路由 /flow/[id]/node/[nid] 用 generateStaticParams 返回空数组 + nginx try_files 兜底
 *
 * 参考：.planning/research/PITFALLS.md #19
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  // 静态导出禁用 Image Optimization
  images: { unoptimized: true },
  // 关闭 server 端 telemetry 弹窗
  experimental: {
    typedRoutes: false,
  },
  // 默认 distDir = '.next'；export 时输出 out/
};

module.exports = nextConfig;
