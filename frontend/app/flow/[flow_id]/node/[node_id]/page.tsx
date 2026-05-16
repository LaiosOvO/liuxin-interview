/**
 * WEB-03 通用节点处理页 — /flow/[flow_id]/node/[node_id]
 *
 * 静态导出策略（PITFALLS #19 + Next.js 15 限制）：
 * - Server Component（本文件）必须导出 generateStaticParams，且不能加 'use client'
 * - 实际渲染交给 ./node-page-client.tsx（'use client'）
 * - generateStaticParams 返回 placeholder 让 Next.js build pass；
 *   真实访问 /flow/<uuid>/node/<uuid>/ 时由 nginx try_files 落到 placeholder/index.html 或客户端 router 处理
 *
 * 业务流程见 NodePageClient 注释。
 */

import { NodePageClient } from './node-page-client';

export function generateStaticParams() {
  return [{ flow_id: 'placeholder', node_id: 'placeholder' }];
}

export default function Page() {
  return <NodePageClient />;
}
