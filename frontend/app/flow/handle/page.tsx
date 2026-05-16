'use client';

/**
 * WEB-02 一键登录入口页
 *
 * URL 格式：/flow/handle?flow_id=...&node_id=...&token=...
 * 关键决策：query string 而非动态路由 — 规避 Next.js 15 issue #79380（dynamicParams + export 路由组合 bug）
 *
 * 流程：
 * 1. 从 query string 提取 token
 * 2. POST /api/auth/exchange { token } 拿 HttpOnly cookie + role / name / redirect_to
 * 3. 把 role / name 存 localStorage（display only）+ 跳转到对应节点页
 * 4. 失败：显示错误 + "重发通知" 按钮（端点未实现 gracefully 占位）
 *
 * 参考：PRD §6.2.2 七步流程
 */

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Loader2, ShieldAlert, MailCheck } from 'lucide-react';
import { authApi, flowApi, ApiError } from '@/lib/api';
import { saveSession } from '@/lib/session';

type Stage = 'loading' | 'exchanging' | 'success' | 'error';

function HandleInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [stage, setStage] = useState<Stage>('loading');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [resendStatus, setResendStatus] = useState<string | null>(null);

  const token = params.get('token');
  const flowId = params.get('flow_id');
  const nodeId = params.get('node_id');

  useEffect(() => {
    if (!token) {
      setStage('error');
      setErrorMsg('链接缺少 token 参数。请重新点击邮件 / IM 中的"立即处理"按钮。');
      return;
    }
    let cancelled = false;
    const run = async () => {
      setStage('exchanging');
      try {
        const result = await authApi.exchange(token);
        if (cancelled) return;
        // 提取 username（token 不解析，从 redirect_to 反推不靠谱，存 name 即可）
        saveSession({
          role: result.role,
          name: result.name,
          username: result.name,
          flow_id: flowId ?? undefined,
          node_id: nodeId ?? undefined,
        });
        setStage('success');
        // 跳转优先级：后端 redirect_to > URL 中的 flow/node > 兜底 /my/flows
        let target = result.redirect_to;
        if (!target) {
          target =
            flowId && nodeId
              ? `/flow/${flowId}/node/${nodeId}/`
              : '/my/flows/';
        }
        router.replace(target);
      } catch (e) {
        if (cancelled) return;
        setStage('error');
        const msg = e instanceof ApiError ? e.message : String(e);
        setErrorMsg(`鉴权失败：${msg}`);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [token, flowId, nodeId, router]);

  const handleResend = async () => {
    if (!flowId) {
      setResendStatus('无 flow_id，无法重发');
      return;
    }
    try {
      await flowApi.resendNotification(flowId);
      setResendStatus('已请求重发，请稍后查收邮件');
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      setResendStatus(`重发失败：${msg}（接口可能未实现，请联系 HR 手工触发）`);
    }
  };

  return (
    <main className="container mx-auto px-4 py-12 max-w-md">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {stage === 'error' ? (
              <>
                <ShieldAlert className="size-5 text-destructive" />
                鉴权失败
              </>
            ) : (
              <>
                <Loader2 className="size-5 animate-spin" />
                正在登录…
              </>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {stage === 'loading' && <p className="text-sm text-muted-foreground">解析链接参数…</p>}
          {stage === 'exchanging' && (
            <p className="text-sm text-muted-foreground">正在用 token 换取 session…</p>
          )}
          {stage === 'success' && (
            <p className="text-sm text-success">登录成功，正在跳转…</p>
          )}
          {stage === 'error' && (
            <>
              <Alert variant="destructive">
                <AlertDescription>{errorMsg ?? '未知错误'}</AlertDescription>
              </Alert>
              <p className="text-xs text-muted-foreground">
                可能原因：链接已使用 / 已过期 / token 被篡改。请联系 HR 重发通知。
              </p>
              {flowId && (
                <div className="space-y-2 pt-2">
                  <Button
                    variant="outline"
                    onClick={handleResend}
                    className="w-full"
                  >
                    <MailCheck className="size-4" />
                    请求重发通知（flow {flowId.slice(0, 8)}…）
                  </Button>
                  {resendStatus && (
                    <p className="text-xs text-muted-foreground">{resendStatus}</p>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

/**
 * 包一层 Suspense — useSearchParams 在 export 模式下需要 Suspense 边界。
 */
export default function HandlePage() {
  return (
    <Suspense
      fallback={
        <main className="container mx-auto px-4 py-12 max-w-md text-center">
          <Loader2 className="size-5 animate-spin inline-block mr-2" />
          加载…
        </main>
      }
    >
      <HandleInner />
    </Suspense>
  );
}
