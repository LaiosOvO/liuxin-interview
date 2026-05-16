'use client';

/**
 * WEB-05 员工 / 个人视角 — /my/flows
 *
 * 显示当前用户名下的流程 + 进度条 + 当前激活节点 + 入口按钮。
 *
 * 数据源：尝试 GET /api/flows + filter by employee_id；fallback mock。
 * 当前用户通过 localStorage session.username 拿。
 *
 * URL 支持 ?last_action=... 显示最近一次操作 toast 提示。
 */

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { NodeStatusBadge } from '@/components/flow/node-status-badge';
import { RoleBanner } from '@/components/role/role-banner';
import { flowApi, ApiError } from '@/lib/api';
import type { FlowDetail, NodeDetail } from '@/lib/api';
import { loadSession } from '@/lib/session';
import {
  ArrowRight,
  CheckCircle2,
  Workflow,
} from 'lucide-react';

type EnrichedFlow = FlowDetail & {
  nodes?: NodeDetail[];
};

function FlowsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const lastAction = params.get('last_action');
  const session = typeof window !== 'undefined' ? loadSession() : null;

  const [flows, setFlows] = useState<EnrichedFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    if (!session?.username) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const all = await flowApi.list();
        if (cancelled) return;
        const mine = all.filter((f) => f.employee_id === session.username);
        // 拉每个流程的节点进度
        const enriched = await Promise.all(
          mine.map(async (f) => {
            try {
              const nodes = await flowApi.listNodes(f.flow_id);
              return { ...f, nodes };
            } catch {
              return f;
            }
          })
        );
        setFlows(enriched);
        setFallback(false);
      } catch (e) {
        if (cancelled) return;
        // 后端 list 端点未实现 → 用当前 session 关联的 flow_id 拉一条
        const msg = e instanceof ApiError ? e.message : String(e);
        setFallback(true);
        if (session.flow_id) {
          try {
            const detail = await flowApi.get(session.flow_id);
            const nodes = await flowApi.listNodes(session.flow_id);
            setFlows([{ ...detail, nodes }]);
            setError(`list 端点暂未实现（${msg}），仅显示当前 session 关联的流程。`);
          } catch (e2) {
            const m2 = e2 instanceof ApiError ? e2.message : String(e2);
            setError(`加载流程失败：${m2}`);
          }
        } else {
          setError(`后端 list 端点不可用：${msg}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [session?.username, session?.flow_id]);

  return (
    <>
      <RoleBanner role={session?.role ?? null} username={session?.username ?? null} />
      <main className="container mx-auto px-4 py-6 max-w-3xl space-y-4">
        <div className="flex items-center gap-2">
          <Workflow className="size-6 text-primary" />
          <h1 className="text-xl font-semibold">我的流程</h1>
        </div>

        {lastAction && (
          <Alert>
            <CheckCircle2 className="size-4 text-success" />
            <AlertDescription>
              已成功提交 [{lastAction}] 决策，流程已推进 / 等待下一节点。
            </AlertDescription>
          </Alert>
        )}

        {fallback && error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!session?.username && (
          <Alert variant="destructive">
            <AlertDescription>
              未检测到登录信息。请通过邮件 / Mattermost 的"立即处理"链接登录。
            </AlertDescription>
          </Alert>
        )}

        {loading && (
          <div className="space-y-3">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {!loading && session?.username && flows.length === 0 && !error && (
          <Card>
            <CardContent className="text-center py-12 text-muted-foreground">
              暂无您名下的流程。
            </CardContent>
          </Card>
        )}

        {!loading && flows.map((flow) => (
          <FlowProgressCard
            key={flow.flow_id}
            flow={flow}
            onAction={(nodeId) =>
              router.push(`/flow/${flow.flow_id}/node/${nodeId}/`)
            }
            onConfirm={() => router.push(`/flow/${flow.flow_id}/applicant-confirm/`)}
          />
        ))}
      </main>
    </>
  );
}

function FlowProgressCard({
  flow,
  onAction,
  onConfirm,
}: {
  flow: EnrichedFlow;
  onAction: (nodeId: string) => void;
  onConfirm: () => void;
}) {
  const nodes = flow.nodes ?? [];
  const total = nodes.length || flow.node_count;
  const done = nodes.filter((n) => n.status === 'done').length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const activeNode = nodes.find((n) => n.status === 'waiting_human');

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">{flow.employee_id} 的离职流程</CardTitle>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              {flow.flow_id}
            </p>
          </div>
          <Badge variant={flow.status === 'completed' ? 'success' : 'default'}>
            {flow.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 进度条 */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>进度</span>
            <span>{done} / {total} 节点完成（{pct}%）</span>
          </div>
          <div className="h-2 bg-muted rounded overflow-hidden">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        <Separator />

        {/* 当前激活节点 */}
        {activeNode ? (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">当前等待处理：</div>
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="font-medium">{activeNode.title || activeNode.name}</div>
                <div className="text-xs text-muted-foreground">
                  Assignee：<span className="font-mono">{activeNode.assignee ?? '—'}</span>
                </div>
              </div>
              <NodeStatusBadge
                status={activeNode.status}
                is_overdue={activeNode.is_overdue}
                evidence_missing={activeNode.evidence_missing}
              />
            </div>
            {/* 申请人最终确认节点走专用页 */}
            <Button
              size="sm"
              onClick={() =>
                activeNode.name === 'applicant_final_confirm'
                  ? onConfirm()
                  : onAction(activeNode.id)
              }
            >
              {activeNode.name === 'applicant_final_confirm' ? '最终确认' : '处理节点'}
              <ArrowRight className="size-4" />
            </Button>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            {flow.status === 'completed' ? '流程已归档完成。' : '暂无等待处理的节点。'}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function MyFlowsPage() {
  return (
    <Suspense
      fallback={
        <main className="container mx-auto px-4 py-6 text-muted-foreground">
          加载中…
        </main>
      }
    >
      <FlowsInner />
    </Suspense>
  );
}
