'use client';

/**
 * 时间线节点 Card — WEB-04 申请人最终确认页
 *
 * 渲染一个 node_result 条目：节点名称 / 状态徽章 / actor / completed_at / result_text
 * 用 border-l 左竖线 + 圆点 模拟时间线效果（不引第三方 timeline 库）。
 */
import { Card, CardContent } from '@/components/ui/card';
import { NodeStatusBadge } from './node-status-badge';
import type { NodeDetail } from '@/lib/api';

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return iso;
  }
}

export type TimelineCardProps = {
  node: NodeDetail;
  /** 排序索引（用于显示 "1. xxx"） */
  index: number;
};

export function TimelineCard({ node, index }: TimelineCardProps) {
  return (
    <div className="relative pl-8 pb-4">
      {/* 左竖线 + 圆点 */}
      <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-border" />
      <div className="absolute left-[-5px] top-3 size-3 rounded-full bg-primary ring-2 ring-background" />

      <Card>
        <CardContent className="pt-4 pb-4 space-y-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-medium">
                {index}. {node.title || node.name}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                <span className="font-mono">{node.assignee ?? '—'}</span>
                {' · '}
                <span>{formatDateTime(node.completed_at ?? node.entered_at)}</span>
              </div>
            </div>
            <NodeStatusBadge
              status={node.status}
              is_overdue={node.is_overdue}
              evidence_missing={node.evidence_missing}
            />
          </div>
          {node.result_text && (
            <div className="text-sm text-muted-foreground whitespace-pre-wrap pt-2 border-t">
              {node.result_text}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
