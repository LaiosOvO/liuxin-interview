'use client';

/**
 * WEB-03 通用节点处理页客户端组件
 *
 * 业务流程：
 * 1. 拉节点详情（GET /api/flows/{flow_id}/nodes，找匹配 id 的项）
 * 2. 若 node_name == 'applicant_final_confirm' → 重定向到申请人确认页
 * 3. 否则渲染通用 NodeForm
 * 4. 提交成功跳转 /my/flows
 */

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { NodeForm } from '@/components/flow/node-form';
import { RoleBanner } from '@/components/role/role-banner';
import { flowApi, ApiError } from '@/lib/api';
import type { NodeDetail } from '@/lib/api';
import { loadSession } from '@/lib/session';
import { ArrowLeft } from 'lucide-react';

export function NodePageClient() {
  const router = useRouter();
  const params = useParams<{ flow_id: string; node_id: string }>();
  const flowId = params.flow_id;
  const nodeId = params.node_id;

  const [node, setNode] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const session = typeof window !== 'undefined' ? loadSession() : null;

  useEffect(() => {
    if (!flowId || !nodeId || flowId === 'placeholder') {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const nodes = await flowApi.listNodes(flowId);
        if (cancelled) return;
        const found = nodes.find((n) => n.id === nodeId);
        if (!found) {
          setError(`节点 ${nodeId} 不存在于流程 ${flowId}`);
          return;
        }
        if (found.name === 'applicant_final_confirm') {
          router.replace(`/flow/${flowId}/applicant-confirm/`);
          return;
        }
        setNode(found);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : String(e);
        setError(`拉取节点失败：${msg}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [flowId, nodeId, router]);

  return (
    <>
      <RoleBanner role={session?.role ?? null} username={session?.username ?? null} />
      <main className="container mx-auto px-4 py-6 max-w-3xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">节点处理</h1>
          <Button variant="ghost" size="sm" onClick={() => router.push('/my/flows/')}>
            <ArrowLeft className="size-4" />
            我的流程
          </Button>
        </div>

        {flowId === 'placeholder' && (
          <Alert>
            <AlertDescription>
              这是静态导出 placeholder。实际访问路径应为 /flow/&lt;uuid&gt;/node/&lt;uuid&gt;/。
            </AlertDescription>
          </Alert>
        )}

        {loading && (
          <Card>
            <CardHeader>
              <Skeleton className="h-6 w-48" />
            </CardHeader>
            <CardContent className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-24 w-full" />
            </CardContent>
          </Card>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!loading && !error && node && session && (
          <NodeForm
            flowId={flowId}
            node={node}
            actor={session.username}
            allowedActions={['advance', 'return', 'reject']}
            description={`流程 ID：${flowId}\n请认真填写处理详情后选择推进 / 退回 / 拒绝。`}
            onSubmitted={(action) => {
              const verb =
                action === 'advance' ? '继续' : action === 'return' ? '退回' : '拒绝';
              router.push(`/my/flows/?last_action=${verb}`);
            }}
          />
        )}

        {!loading && !error && node && !session && (
          <Alert variant="destructive">
            <AlertDescription>
              未检测到登录信息，请重新点击邮件链接 / 走 /flow/handle 一键登录入口。
            </AlertDescription>
          </Alert>
        )}
      </main>
    </>
  );
}
