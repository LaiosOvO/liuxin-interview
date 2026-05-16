'use client';

/**
 * 节点状态徽章 — 包含 status + TIMEOUT-04 红黄标签
 *
 * status: pending / waiting_human / done / returned / rejected / failed
 * is_overdue: true → 显示 "⏰ 已超时" 红色
 * evidence_missing: true → 显示 "⚠️ 证据待补充" 黄色
 *
 * 对应 REQ：TIMEOUT-04
 */
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, CheckCircle2, Clock, RotateCcw, XCircle, AlarmClock } from 'lucide-react';

const STATUS_LABEL: Record<string, string> = {
  pending: '待开始',
  waiting_human: '待处理',
  done: '已完成',
  returned: '已退回',
  rejected: '已拒绝',
  failed: '失败',
  skipped: '已跳过',
};

type StatusVariant = 'default' | 'secondary' | 'destructive' | 'outline' | 'warning' | 'success';

const STATUS_VARIANT: Record<string, StatusVariant> = {
  pending: 'outline',
  waiting_human: 'warning',
  done: 'success',
  returned: 'destructive',
  rejected: 'destructive',
  failed: 'destructive',
  skipped: 'secondary',
};

function StatusIcon({ status }: { status: string }) {
  if (status === 'done') return <CheckCircle2 className="size-3" />;
  if (status === 'waiting_human') return <Clock className="size-3" />;
  if (status === 'returned') return <RotateCcw className="size-3" />;
  if (status === 'rejected' || status === 'failed') return <XCircle className="size-3" />;
  return <Clock className="size-3" />;
}

export type NodeStatusBadgeProps = {
  status: string;
  is_overdue?: boolean;
  evidence_missing?: boolean;
  className?: string;
};

/** 节点状态主徽章 + 超时 / 证据缺失辅助徽章 */
export function NodeStatusBadge({
  status,
  is_overdue,
  evidence_missing,
  className,
}: NodeStatusBadgeProps) {
  const label = STATUS_LABEL[status] ?? status;
  const variant = STATUS_VARIANT[status] ?? 'default';

  return (
    <div className={`inline-flex flex-wrap items-center gap-1.5 ${className ?? ''}`}>
      <Badge variant={variant} className="gap-1">
        <StatusIcon status={status} />
        {label}
      </Badge>
      {is_overdue && (
        <Badge variant="destructive" className="gap-1">
          <AlarmClock className="size-3" />
          已超时
        </Badge>
      )}
      {evidence_missing && (
        <Badge variant="warning" className="gap-1">
          <AlertTriangle className="size-3" />
          证据待补充
        </Badge>
      )}
    </div>
  );
}
