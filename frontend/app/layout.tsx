/**
 * 根 Layout — 静态导出模式下不能放 server-only 代码。
 *
 * 注意：layout 本身可以不是 'use client'（不含 hook）；但所有子页面必须 'use client'，
 * 因为 output: 'export' 下 Next.js 不允许动态 server rendering。
 */
import './globals.css';
import type { Metadata } from 'next';
import { Footer } from '@/components/footer';

export const metadata: Metadata = {
  title: '离职流程系统',
  description: 'AI 驱动的离职流程执行系统',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen flex flex-col">
        <div className="flex-1">{children}</div>
        <Footer />
      </body>
    </html>
  );
}
