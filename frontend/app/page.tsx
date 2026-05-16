'use client';

/**
 * 首页 /
 *
 * 简化逻辑：
 * - 读 localStorage session 决定跳哪里：
 *   - role=hr → /hr/dashboard
 *   - 其他 role → /my/flows
 *   - 无 session → 显示登录提示（用户必须从邮件 / IM 一键登录进来）
 *
 * 不做 cookie 自动鉴权 — HttpOnly cookie 前端读不到；
 * 实际鉴权由后端 /api/auth/exchange 完成后存 session 元信息。
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { loadSession } from '@/lib/session';
import { MailQuestion, Workflow } from 'lucide-react';

export default function IndexPage() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const session = loadSession();
    if (!session) {
      setChecked(true);
      return;
    }
    if (session.role === 'hr' || session.role === 'admin') {
      router.replace('/hr/dashboard/');
    } else {
      router.replace('/my/flows/');
    }
  }, [router]);

  if (!checked) {
    return (
      <main className="container mx-auto px-4 py-12 max-w-md text-center text-muted-foreground">
        加载中…
      </main>
    );
  }

  return (
    <main className="container mx-auto px-4 py-12 max-w-md space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Workflow className="size-5" />
            离职流程系统
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            AI 驱动的离职流程执行系统 — 双层状态（LangGraph 引擎 + 业务表）；
            10 节点 DAG；双通道通知（邮件 + Mattermost）；
            一键登录入口；GLM 摘要 / 报告辅助。
          </p>
          <Alert>
            <MailQuestion className="size-4" />
            <AlertDescription>
              请通过邮件 / Mattermost 收到的"立即处理"链接登录系统。
              所有操作通过一键登录入口进入，无需账号密码。
            </AlertDescription>
          </Alert>
          <p className="text-xs text-muted-foreground font-mono">
            链接格式：/flow/handle?flow_id=...&amp;node_id=...&amp;token=...
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
