'use client';

/**
 * WEB-04 申请人最终确认页 — /flow/[flow_id]/applicant-confirm
 *
 * 在通用 NodeForm 基础上额外渲染：
 * - 顶部：GLM 摘要段（payload.glm_summary，由 backend applicant_summary_service 注入）
 *   带 🤖 AI 生成 角标 + AI_DISCLAIMER
 * - 中部：节点结果时间线（垂直列表，每节点一张 TimelineCard）
 * - 底部：通用 NodeForm 但只暴露 "确认 / 退回" 两个按钮（无拒绝 — PRD §4.5.2）
 *
 * 数据来源：
 * 1. listNodes 拉所有节点（过滤出 status=done 的做时间线 + 找 applicant_final_confirm 节点）
 * 2. applicant_final_confirm 节点的 payload.glm_summary 是 GLM 生成的摘要
 */

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import { NodeForm } from '@/components/flow/node-form';
import { TimelineCard } from '@/components/flow/timeline-card';
import { RoleBanner } from '@/components/role/role-banner';
import { AIDisclaimer } from '@/components/ai-disclaimer';
import { flowApi, ApiError } from '@/lib/api';
import type { NodeDetail } from '@/lib/api';
import { loadSession } from '@/lib/session';
import { ClipboardCheck } from 'lucide-react';

export function ApplicantConfirmClient() {
  const router = useRouter();
  const params = useParams<{ flow_id: string }>();
  const flowId = params.flow_id;

  const [nodes, setNodes] = useState<NodeDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const session = typeof window !== 'undefined' ? loadSession() : null;

  useEffect(() => {
    if (!flowId) return;
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await flowApi.listNodes(flowId);
        if (cancelled) return;
        setNodes(list);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : String(e);
        setError(`拉取流程节点失败：${msg}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [flowId]);

  const confirmNode = useMemo(
    () => nodes.find((n) => n.name === 'applicant_final_confirm') ?? null,
    [nodes]
  );

  /** 时间线节点：所有已完成的节点（排除 confirm 节点本身） */
  const timelineNodes = useMemo(
    () =>
      nodes
        .filter(
          (n) =>
            n.name !== 'applicant_final_confirm' &&
            (n.status === 'done' || n.status === 'returned' || n.status === 'rejected')
        )
        .sort((a, b) => {
          const ta = a.completed_at ?? a.entered_at ?? '';
          const tb = b.completed_at ?? b.entered_at ?? '';
          return ta.localeCompare(tb);
        }),
    [nodes]
  );

  /** GLM 摘要 — 从 confirmNode.payload.glm_summary 拿 */
  const glmSummary = useMemo(() => {
    if (!confirmNode?.payload) return null;
    const v = (confirmNode.payload as Record<string, unknown>)['glm_summary'];
    return typeof v === 'string' && v.trim() ? v : null;
  }, [confirmNode]);

  return (
    <>
      <RoleBanner role={session?.role ?? null} username={session?.username ?? null} />
      <main className="container mx-auto px-4 py-6 max-w-3xl space-y-4">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="size-6 text-primary" />
          <h1 className="text-xl font-semibold">离职流程最终确认</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          请仔细核对下方所有环节的执行记录，确认无误后点击「确认」推进归档；如有异议请「退回」由 HR 复核。
        </p>

        {loading && (
          <div className="space-y-3">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!loading && !error && (
          <>
            {/* GLM 摘要段（顶部，带 AI 角标 + disclaimer） */}
            {glmSummary && (
              <section>
                <h2 className="text-sm font-medium mb-2 text-muted-foreground">
                  AI 自动生成的流程摘要
                </h2>
                <AIDisclaimer withHeader>{glmSummary}</AIDisclaimer>
              </section>
            )}

            {/* 节点时间线 */}
            <section>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">执行记录时间线</CardTitle>
                </CardHeader>
                <CardContent>
                  {timelineNodes.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      暂无已完成节点。
                    </p>
                  ) : (
                    <div className="space-y-0">
                      {timelineNodes.map((n, i) => (
                        <TimelineCard key={n.id} node={n} index={i + 1} />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </section>

            <Separator />

            {/* 决策表单 — 仅 advance / return */}
            {confirmNode && session && (
              <NodeForm
                flowId={flowId}
                node={confirmNode}
                actor={session.username}
                allowedActions={['advance', 'return']}
                description={'请填写最终确认意见（如"已核对所有节点，无异议"或退回理由）。'}
                onSubmitted={(action) => {
                  const verb = action === 'advance' ? '确认' : '退回';
                  router.push(`/my/flows/?last_action=${verb}`);
                }}
              />
            )}

            {confirmNode && !session && (
              <Alert variant="destructive">
                <AlertDescription>
                  未检测到登录信息，请重新点击邮件链接登录后再操作。
                </AlertDescription>
              </Alert>
            )}

            {!confirmNode && (
              <Alert>
                <AlertDescription>
                  当前流程尚未进入"申请人最终确认"节点，请等待 HR 终审完成。
                </AlertDescription>
              </Alert>
            )}
          </>
        )}
      </main>
    </>
  );
}

// generateStaticParams 必须放在 server component（同目录 page.tsx），不在客户端组件里。
