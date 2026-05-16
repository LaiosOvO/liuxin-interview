/**
 * 客户端可读取的运行时配置（来自 NEXT_PUBLIC_* env，build 时注入）
 *
 * - NEXT_PUBLIC_API_URL：后端基址（开发 http://localhost:8000；prod nginx 同源用空串）
 * - NEXT_PUBLIC_APP_MODE：'demo' | 'prod'（演示模式 footer 要标，防 PITFALLS #10）
 *
 * 注意：Next.js export 模式 env 在 build 时已经被替换成字面量，运行时无法再读 process.env。
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export const APP_MODE = (process.env.NEXT_PUBLIC_APP_MODE ?? 'demo') as
  | 'demo'
  | 'prod';

/** 角色 → 中文 — 与 backend ROLE_CN_MAP 保持一致 */
export const ROLE_CN_MAP: Record<string, string> = {
  applicant: '申请人',
  manager: '上级',
  hr: 'HR',
  it_admin: '设备管理员',
  finance: '财务',
  legal: '法务',
  kb_owner: '知识库负责人',
  archivist: '档案管理员',
  admin: '管理员',
};

export function roleLabel(role: string | null | undefined): string {
  if (!role) return '未知角色';
  return ROLE_CN_MAP[role] ?? role;
}

/** AI disclaimer — 必须与 backend services/ai_disclaimer.py 完全一致 */
export const AI_DISCLAIMER =
  '*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*';
export const AI_HEADER = '🤖 AI 生成';
