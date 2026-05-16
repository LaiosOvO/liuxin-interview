/**
 * 客户端 session 元信息存储（display only）
 *
 * 后端 session cookie 是 HttpOnly — JS 拿不到；
 * 但我们需要在前端 UI 显示 "当前角色 / username"。
 * 解决：/api/auth/exchange 成功后把 role/name 存 localStorage，UI 读这里。
 *
 * 注意：这只是显示用，**绝不**用 localStorage 做鉴权判断 — 鉴权完全靠后端 cookie。
 */
export type SessionInfo = {
  role: string;
  name: string;
  username: string;
  flow_id?: string;
  node_id?: string;
};

const KEY = 'offboarding.session';

export function saveSession(info: SessionInfo): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(info));
  } catch {
    // ignore（quota / private 模式）
  }
}

export function loadSession(): SessionInfo | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw) as SessionInfo;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
