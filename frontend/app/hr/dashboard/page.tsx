'use client';

/**
 * WEB-05 HR Dashboard — /hr/dashboard
 *
 * 渲染所有流程实例（表格 + 状态过滤 + 搜索 + 重发通知）；
 * 顶部统计卡片（总数 / 进行中 / 超时数 / 证据缺失数）。
 *
 * 数据源：GET /api/flows（Phase 1-4 暂未实现 list 端点 → gracefully fallback 用 mock 数据，TODO 注释）
 * 重发通知端点同样可能未实现 → catch 后展示"已请求"占位提示。
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { RoleBanner } from '@/components/role/role-banner';
import { flowApi, ApiError } from '@/lib/api';
import type { FlowDetail } from '@/lib/api';
import { loadSession } from '@/lib/session';
import {
  AlertTriangle,
  AlarmClock,
  CheckCircle2,
  Loader2,
  MailCheck,
  Search,
  Workflow,
} from 'lucide-react';

type StatusFilter = 'all' | 'active' | 'completed' | 'stuck';

/** 当后端 list 端点缺失时的 mock 兜底，方便页面演示。 */
const MOCK_FLOWS: FlowDetail[] = [
  {
    flow_id: '00000000-0000-0000-0000-000000000001',
    employee_id: 'zhang.san',
    template: 'standard_offboarding',
    status: 'active',
    started_at: '2026-05-16T10:00:00',
    completed_at: null,
    node_count: 10,
    current_node: {
      id: '11111111-1111-1111-1111-111111111111',
      name: 'manager_review',
      title: '上级审批',
      status: 'waiting_human',
      assignee: 'li.si',
    },
  },
  {
    flow_id: '00000000-0000-0000-0000-000000000002',
    employee_id: 'wang.wu',
    template: 'standard_offboarding',
    status: 'active',
    started_at: '2026-05-15T14:20:00',
    completed_at: null,
    node_count: 10,
    current_node: {
      id: '22222222-2222-2222-2222-222222222222',
      name: 'device_return',
      title: '设备归还',
      status: 'waiting_human',
      assignee: 'it.charlie',
    },
  },
  {
    flow_id: '00000000-0000-0000-0000-000000000003',
    employee_id: 'qian.qi',
    template: 'standard_offboarding',
    status: 'completed',
    started_at: '2026-05-10T09:00:00',
    completed_at: '2026-05-13T16:30:00',
    node_count: 10,
    current_node: null,
  },
];

function progressText(flow: FlowDetail): string {
  if (flow.status === 'completed') return `${flow.node_count}/${flow.node_count}`;
  // 没有 current_node 信息时假设是 0；有则按当前节点位置估算
  if (!flow.current_node) return '—';
  return `进行中（当前：${flow.current_node.title}）`;
}

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'success' | 'warning' | 'destructive' {
  if (status === 'completed') return 'success';
  if (status === 'active') return 'default';
  if (status === 'failed') return 'destructive';
  return 'secondary';
}

export default function HRDashboardPage() {
  const router = useRouter();
  const session = typeof window !== 'undefined' ? loadSession() : null;
  const [flows, setFlows] = useState<FlowDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [fallback, setFallback] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [search, setSearch] = useState('');
  const [resendingId, setResendingId] = useState<string | null>(null);
  const [resendResult, setResendResult] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await flowApi.list();
        if (cancelled) return;
        setFlows(list);
        setFallback(false);
      } catch (e) {
        if (cancelled) return;
        // TODO: 后端 list 端点未实现（Phase 1-4 仅有 POST / GET-by-id）→ fallback 演示
        // 实现路径：backend/src/offboarding_flow/api/flows.py 加 @router.get("") +
        // FlowService.list_flows() 读 flow_repo.list_all()
        const msg = e instanceof ApiError ? e.message : String(e);
        setError(`后端 list 端点暂不可用（${msg}），使用本地 mock 数据演示。`);
        setFlows(MOCK_FLOWS);
        setFallback(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 过滤 + 搜索 */
  const visibleFlows = useMemo(() => {
    let result = flows;
    if (filter !== 'all') {
      result = result.filter((f) => {
        if (filter === 'active') return f.status === 'active';
        if (filter === 'completed') return f.status === 'completed';
        // stuck = 暂时定义为有 current_node 且状态为 waiting_human
        if (filter === 'stuck')
          return f.status === 'active' && f.current_node?.status === 'waiting_human';
        return true;
      });
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(
        (f) =>
          f.employee_id.toLowerCase().includes(q) ||
          f.flow_id.toLowerCase().includes(q) ||
          (f.current_node?.assignee ?? '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [flows, filter, search]);

  /** 统计 — 简化版（mock / 真实数据都适用） */
  const stats = useMemo(() => {
    const total = flows.length;
    const active = flows.filter((f) => f.status === 'active').length;
    const completed = flows.filter((f) => f.status === 'completed').length;
    // 真实超时数 / 证据缺失数需要节点级聚合，这里 mock 演示
    const overdue = flows.filter(
      (f) => f.current_node && f.status === 'active'
    ).length;
    return { total, active, completed, overdue };
  }, [flows]);

  const handleResend = async (flowId: string) => {
    setResendingId(flowId);
    try {
      await flowApi.resendNotification(flowId);
      setResendResult((s) => ({ ...s, [flowId]: '已请求重发' }));
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      setResendResult((s) => ({
        ...s,
        [flowId]: `失败（${msg}，可能后端未实现 /api/notifications/${flowId}/resend）`,
      }));
    } finally {
      setResendingId(null);
    }
  };

  return (
    <>
      <RoleBanner role={session?.role ?? null} username={session?.username ?? null} />
      <main className="container mx-auto px-4 py-6 max-w-6xl space-y-6">
        <div className="flex items-center gap-2">
          <Workflow className="size-6 text-primary" />
          <h1 className="text-xl font-semibold">HR 流程总览</h1>
        </div>

        {fallback && error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* 统计卡片 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="流程总数" value={stats.total} icon={<Workflow className="size-5" />} />
          <StatCard label="进行中" value={stats.active} icon={<Loader2 className="size-5" />} variant="default" />
          <StatCard label="已完成" value={stats.completed} icon={<CheckCircle2 className="size-5" />} variant="success" />
          <StatCard label="疑似卡点 / 超时" value={stats.overdue} icon={<AlarmClock className="size-5" />} variant="warning" />
        </div>

        {/* 过滤工具栏 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">流程列表</CardTitle>
            <CardDescription>
              点击行进入详情；右侧"重发通知"按钮触发后端 outbox 重排（端点未落地时占位）
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex gap-1">
                {(['all', 'active', 'completed', 'stuck'] as StatusFilter[]).map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant={filter === s ? 'default' : 'outline'}
                    onClick={() => setFilter(s)}
                  >
                    {s === 'all'
                      ? '全部'
                      : s === 'active'
                        ? '进行中'
                        : s === 'completed'
                          ? '已完成'
                          : '卡点'}
                  </Button>
                ))}
              </div>
              <div className="relative flex-1 max-w-xs">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                <Input
                  placeholder="搜索 employee / flow_id / assignee"
                  className="pl-8"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>

            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>员工</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>当前节点 / Assignee</TableHead>
                    <TableHead>进度</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleFlows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                        无匹配流程
                      </TableCell>
                    </TableRow>
                  )}
                  {visibleFlows.map((flow) => (
                    <TableRow key={flow.flow_id}>
                      <TableCell>
                        <div className="font-medium">{flow.employee_id}</div>
                        <div className="text-xs text-muted-foreground font-mono">
                          {flow.flow_id.slice(0, 8)}…
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusBadgeVariant(flow.status)}>
                          {flow.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {flow.current_node ? (
                          <div>
                            <div className="text-sm">{flow.current_node.title}</div>
                            <div className="text-xs text-muted-foreground font-mono">
                              @{flow.current_node.assignee ?? '—'}
                            </div>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-sm">{progressText(flow)}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <div className="flex gap-1">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => router.push(`/flow/${flow.flow_id}/applicant-confirm/`)}
                            >
                              详情
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={resendingId === flow.flow_id}
                              onClick={() => handleResend(flow.flow_id)}
                            >
                              {resendingId === flow.flow_id ? (
                                <Loader2 className="size-3 animate-spin" />
                              ) : (
                                <MailCheck className="size-3" />
                              )}
                              重发通知
                            </Button>
                          </div>
                          {resendResult[flow.flow_id] && (
                            <div className="text-xs text-muted-foreground">
                              {resendResult[flow.flow_id]}
                            </div>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}

function StatCard({
  label,
  value,
  icon,
  variant = 'secondary',
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  variant?: 'default' | 'secondary' | 'success' | 'warning';
}) {
  const variantClass: Record<string, string> = {
    default: 'text-primary',
    secondary: 'text-muted-foreground',
    success: 'text-success',
    warning: 'text-warning',
  };
  return (
    <Card>
      <CardContent className="pt-6 pb-4 flex items-center justify-between">
        <div>
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-2xl font-bold">{value}</div>
        </div>
        <div className={variantClass[variant]}>
          {icon}
          <AlertTriangle className="hidden" />
        </div>
      </CardContent>
    </Card>
  );
}
