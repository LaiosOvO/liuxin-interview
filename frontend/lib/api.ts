/**
 * API client — 解析后端统一 envelope `{success, data, error, meta}`
 *
 * 关键决策（Phase 5）：
 * - 自动带 cookie（credentials: 'include'），用于 session cookie
 * - 后端 URL 走 NEXT_PUBLIC_API_URL 环境变量，默认 http://localhost:8000
 * - 生产 nginx 同源时设为空字符串
 * - envelope success=false 抛 ApiError（带 message）
 *
 * 参考：backend/src/offboarding_flow/api/envelope.py
 */
import { API_BASE_URL } from './config';

export type ApiEnvelope<T> = {
  success: boolean;
  data: T | null;
  error: string | null;
  meta?: Record<string, unknown> | null;
};

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

type FetchOptions = Omit<RequestInit, 'body'> & {
  body?: unknown;
};

async function request<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { body, headers, ...rest } = options;
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;

  const init: RequestInit = {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(headers ?? {}),
    },
    ...rest,
  };

  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }

  let resp: Response;
  try {
    resp = await fetch(url, init);
  } catch (e) {
    throw new ApiError(
      `网络请求失败：${e instanceof Error ? e.message : String(e)}`,
      0
    );
  }

  // 解析 envelope（即使 4xx/5xx 也尝试，因为后端约定统一返回 envelope）
  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await resp.json()) as ApiEnvelope<T>;
  } catch {
    // 非 JSON 响应：仍按 HTTP 状态码处理
    if (!resp.ok) {
      throw new ApiError(`HTTP ${resp.status}：${resp.statusText}`, resp.status);
    }
    throw new ApiError('响应不是合法 JSON', resp.status);
  }

  if (!envelope.success) {
    throw new ApiError(
      envelope.error ?? `HTTP ${resp.status}`,
      resp.status,
      envelope
    );
  }

  return envelope.data as T;
}

export const api = {
  get: <T>(path: string, options?: FetchOptions) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: FetchOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: FetchOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  delete: <T>(path: string, options?: FetchOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};

// ===== 业务专用辅助 =====

export type ExchangeResult = {
  redirect_to: string;
  role: string;
  name: string;
};

export type NodeDetail = {
  id: string;
  name: string;
  title: string;
  status: string;
  assignee: string | null;
  result_text: string | null;
  is_overdue: boolean;
  evidence_missing?: boolean;
  entered_at: string | null;
  completed_at: string | null;
  payload?: Record<string, unknown> | null;
};

export type FlowDetail = {
  flow_id: string;
  employee_id: string;
  template: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  node_count: number;
  current_node?: {
    id: string;
    name: string;
    title: string;
    status: string;
    assignee: string | null;
  } | null;
};

export type SubmitActionBody = {
  action: 'advance' | 'return' | 'reject';
  result_text: string;
  actor: string;
};

export const authApi = {
  exchange: (token: string) =>
    api.post<ExchangeResult>('/api/auth/exchange', { token }),
  logout: () => api.post<{ message: string }>('/api/auth/logout'),
};

export const flowApi = {
  get: (flowId: string) => api.get<FlowDetail>(`/api/flows/${flowId}`),
  listNodes: (flowId: string) =>
    api.get<NodeDetail[]>(`/api/flows/${flowId}/nodes`),
  submitAction: (flowId: string, nodeId: string, body: SubmitActionBody) =>
    api.post<unknown>(
      `/api/flows/${flowId}/nodes/${nodeId}/actions`,
      body
    ),
  // 后端 list 端点（Phase 5 时未必落地，UI gracefully fallback）
  list: () => api.get<FlowDetail[]>('/api/flows'),
  resendNotification: (flowId: string) =>
    api.post<{ message: string }>(`/api/notifications/${flowId}/resend`),
};
