'use client';

/**
 * 通用节点处理表单 NodeForm — WEB-03 核心组件
 *
 * 形态：
 * - 节点说明（只读）
 * - 详情文本输入框（必填 + 长度校验）
 * - 三态按钮（继续=蓝 default / 退回=黄 warning / 拒绝=红 destructive）
 * - 退回 / 拒绝触发 confirm dialog（reason 必填）
 * - 节点状态徽章（含 TIMEOUT-04 超时 / 证据待补充标签）
 *
 * 不在此组件内做 router 跳转 — 由调用方传 onSubmitted 回调处理推进结果。
 */
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { NodeStatusBadge } from './node-status-badge';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { flowApi, ApiError } from '@/lib/api';
import type { NodeDetail, SubmitActionBody } from '@/lib/api';
import { CheckCircle2, RotateCcw, XCircle } from 'lucide-react';

const baseSchema = z.object({
  result_text: z
    .string()
    .min(1, '请填写节点处理详情'),
});

export type NodeFormProps = {
  flowId: string;
  node: NodeDetail;
  /** 当前登录用户 username（提交 action 必填） */
  actor: string;
  /**
   * 支持的动作集合 — 申请人确认页只传 ['advance', 'return']；普通节点传三个。
   */
  allowedActions?: Array<'advance' | 'return' | 'reject'>;
  /** 提交成功后的回调（调用方负责跳转） */
  onSubmitted?: (action: 'advance' | 'return' | 'reject') => void;
  /** 节点说明 — 可选，默认从 node.title + node.payload.description 推 */
  description?: React.ReactNode;
  /** 顶部额外内容（如申请人确认页的时间线） */
  topSlot?: React.ReactNode;
};

export function NodeForm({
  flowId,
  node,
  actor,
  allowedActions = ['advance', 'return', 'reject'],
  onSubmitted,
  description,
  topSlot,
}: NodeFormProps) {
  const [pendingAction, setPendingAction] = useState<
    'advance' | 'return' | 'reject' | null
  >(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const form = useForm({
    resolver: zodResolver(baseSchema),
    defaultValues: {
      result_text: node.result_text ?? '',
    },
  });

  const submit = async (action: 'advance' | 'return' | 'reject') => {
    setSubmitting(true);
    setError(null);
    try {
      const body: SubmitActionBody = {
        action,
        result_text: form.getValues('result_text'),
        actor,
      };
      await flowApi.submitAction(flowId, node.id, body);
      setPendingAction(null);
      onSubmitted?.(action);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      setError(`提交失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  // 触发三态按钮 — advance 直接提交；return / reject 走 confirm dialog
  const handleClick = async (action: 'advance' | 'return' | 'reject') => {
    const valid = await form.trigger();
    if (!valid) return;
    if (action === 'advance') {
      void submit(action);
    } else {
      setPendingAction(action);
    }
  };

  const isDisabled = node.status !== 'waiting_human';

  return (
    <>
      {topSlot}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle>{node.title || node.name}</CardTitle>
              <p className="text-sm text-muted-foreground mt-1 font-mono">
                节点 ID：{node.name}
              </p>
            </div>
            <NodeStatusBadge
              status={node.status}
              is_overdue={node.is_overdue}
              evidence_missing={node.evidence_missing}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {description && (
            <>
              <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                {description}
              </div>
              <Separator />
            </>
          )}
          {isDisabled && (
            <Alert variant="destructive">
              <AlertDescription>
                当前节点不处于 waiting_human 状态（{node.status}），无法提交决策。
              </AlertDescription>
            </Alert>
          )}
          <Form {...form}>
            <form
              className="space-y-4"
              onSubmit={(e) => e.preventDefault()}
            >
              <FormField
                control={form.control}
                name="result_text"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>节点处理详情（必填）</FormLabel>
                    <FormControl>
                      <Textarea
                        rows={6}
                        placeholder="请填写处理结果、备注、证据说明等…"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      此内容将作为 result_text 写入流程审计日志，并出现在申请人最终确认邮件中。
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <div className="flex flex-wrap gap-2 pt-2">
                {allowedActions.includes('advance') && (
                  <Button
                    type="button"
                    variant="default"
                    disabled={isDisabled || submitting}
                    onClick={() => handleClick('advance')}
                  >
                    <CheckCircle2 className="size-4" />
                    继续
                  </Button>
                )}
                {allowedActions.includes('return') && (
                  <Button
                    type="button"
                    variant="warning"
                    disabled={isDisabled || submitting}
                    onClick={() => handleClick('return')}
                  >
                    <RotateCcw className="size-4" />
                    退回
                  </Button>
                )}
                {allowedActions.includes('reject') && (
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={isDisabled || submitting}
                    onClick={() => handleClick('reject')}
                  >
                    <XCircle className="size-4" />
                    拒绝
                  </Button>
                )}
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={pendingAction === 'return' || pendingAction === 'reject'}
        onOpenChange={(open) => !open && setPendingAction(null)}
        title={pendingAction === 'reject' ? '确认拒绝此节点？' : '确认退回此节点？'}
        desc={
          pendingAction === 'reject'
            ? '拒绝可能导致整个流程终止（取决于流程模板规则），请确认 reason 已写入"节点处理详情"。'
            : '退回会回退到流程模板配置的上游节点，由上游 assignee 重新处理。请确认 reason 已写入"节点处理详情"。'
        }
        confirmText={pendingAction === 'reject' ? '确认拒绝' : '确认退回'}
        destructive
        isLoading={submitting}
        handleConfirm={() => pendingAction && void submit(pendingAction)}
      />
    </>
  );
}
