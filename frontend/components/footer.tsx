'use client';

/**
 * Footer — 必须显式显示当前 APP_MODE（PITFALLS #10 防演示模式上线）
 */
import { APP_MODE } from '@/lib/config';
import { cn } from '@/lib/utils';

export function Footer() {
  const isDemo = APP_MODE === 'demo';
  return (
    <footer className="border-t bg-muted/30 py-3 px-4 text-xs text-muted-foreground flex items-center justify-between">
      <div>
        离职流程系统 · v0.1 · Phase 5 前端
      </div>
      <div className="flex items-center gap-2">
        <span>运行模式：</span>
        <span
          className={cn(
            'px-2 py-0.5 rounded font-mono font-medium',
            isDemo
              ? 'bg-warning/20 text-warning border border-warning/40'
              : 'bg-success/20 text-success border border-success/40'
          )}
        >
          {APP_MODE.toUpperCase()}
        </span>
        {isDemo && (
          <span className="text-warning">所有邮件路由到 DEMO_INBOX</span>
        )}
      </div>
    </footer>
  );
}
