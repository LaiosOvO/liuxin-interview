'use client';

/**
 * AI 输出 wrapper — 角标 + disclaimer
 *
 * 必须与 backend services/ai_disclaimer.py 文案严格一致（LLM-06 / PRD §15.3）。
 * 用于 GLM 摘要展示。
 */
import { AI_DISCLAIMER, AI_HEADER } from '@/lib/config';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Sparkles } from 'lucide-react';

export type AIDisclaimerProps = {
  /** AI 生成的正文（已 strip 过） */
  children: React.ReactNode;
  /** 是否显示头部角标（短建议 true；markdown 报告 false 防破坏 # 标题） */
  withHeader?: boolean;
  /** 自定义 className */
  className?: string;
};

/**
 * 包裹 AI 输出，展示角标 + body + disclaimer。
 *
 * 与后端 `wrap_ai_output(text, with_header=True)` 行为对齐。
 */
export function AIDisclaimer({
  children,
  withHeader = true,
  className,
}: AIDisclaimerProps) {
  return (
    <Alert className={className}>
      {withHeader && (
        <div className="flex items-center gap-2 mb-2 text-sm font-medium text-primary">
          <Sparkles className="size-4" />
          <span>{AI_HEADER}</span>
        </div>
      )}
      <AlertDescription>
        <div className="prose prose-sm max-w-none whitespace-pre-wrap text-foreground">
          {children}
        </div>
        <div className="mt-3 pt-2 border-t text-xs text-muted-foreground italic">
          {AI_DISCLAIMER}
        </div>
      </AlertDescription>
    </Alert>
  );
}
