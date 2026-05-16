'use client';

/**
 * 确认对话框（极简版）
 *
 * 用 Dialog 而非 AlertDialog（减一个依赖；UX 上对本项目"决策确认"场景已够用）。
 * 来源：参考 shadcn-admin/src/components/confirm-dialog.tsx 简化版。
 */
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  desc: React.ReactNode;
  cancelBtnText?: string;
  confirmText?: React.ReactNode;
  destructive?: boolean;
  isLoading?: boolean;
  disabled?: boolean;
  className?: string;
  children?: React.ReactNode;
  handleConfirm: () => void;
};

export function ConfirmDialog(props: ConfirmDialogProps) {
  const {
    open,
    onOpenChange,
    title,
    desc,
    children,
    className,
    confirmText = '确认',
    cancelBtnText = '取消',
    destructive,
    isLoading,
    disabled = false,
    handleConfirm,
  } = props;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn('sm:max-w-md', className)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div>{desc}</div>
          </DialogDescription>
        </DialogHeader>
        {children && <div className="py-2">{children}</div>}
        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            {cancelBtnText}
          </Button>
          <Button
            type="button"
            variant={destructive ? 'destructive' : 'default'}
            onClick={handleConfirm}
            disabled={disabled || isLoading}
          >
            {isLoading ? '处理中…' : confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
