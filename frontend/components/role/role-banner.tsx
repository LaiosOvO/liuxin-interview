'use client';

/**
 * 顶部角色横幅 — 显示 "当前角色：xxx（username）"
 *
 * 从 cookie 解析不到 session 时，由调用方判断（cookie HttpOnly 前端拿不到）。
 * 这里只展示传入的 props。session 信息来自 /api/auth/exchange 的 redirect_to / role / name 响应。
 */
import { Badge } from '@/components/ui/badge';
import { roleLabel } from '@/lib/config';
import { LogIn, UserCog } from 'lucide-react';

export type RoleBannerProps = {
  role: string | null;
  username: string | null;
};

export function RoleBanner({ role, username }: RoleBannerProps) {
  if (!role || !username) {
    return (
      <div className="border-b bg-muted/40 px-4 py-2 flex items-center gap-2 text-sm">
        <LogIn className="size-4 text-muted-foreground" />
        <span className="text-muted-foreground">未登录</span>
      </div>
    );
  }
  return (
    <div className="border-b bg-muted/40 px-4 py-2 flex items-center gap-2 text-sm">
      <UserCog className="size-4 text-muted-foreground" />
      <span className="text-muted-foreground">当前角色：</span>
      <Badge variant="secondary">{roleLabel(role)}</Badge>
      <span className="font-mono text-xs text-muted-foreground">
        ({username})
      </span>
    </div>
  );
}
