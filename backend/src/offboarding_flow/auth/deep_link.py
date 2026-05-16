"""深链 URL 构造 — R2 方案 A query string 格式（PRD §6.2 + SUMMARY R2 锁定）。

格式：{base_url}/flow/handle?flow_id=xxx&node_id=yyy&token=zzz

约定：
- 不用 path param（规避 Next.js 15 issue #79380 静态导出动态路由）
- 不用 URL fragment（不发服务器）
- token 不再次 URL-encode（jwt 本身已 URL-safe base64）
"""

from __future__ import annotations

from urllib.parse import urlencode

from .schemas import JWTPayload

_HANDLE_PATH = "/flow/handle"


def build_deep_link(token: str, payload: JWTPayload, *, base_url: str) -> str:
    """构造一键登录深链 URL（query string 格式）。

    Args:
        token: JWT 字符串（已 encode）
        payload: JWT payload（提取 flow_id / node_id 拼到 query）
        base_url: DEEPLINK_BASE_URL（自动剥尾斜杠）

    Returns:
        完整 URL 例：http://192.168.2.44:3000/flow/handle?flow_id=...&node_id=...&token=...
    """
    base = base_url.rstrip("/")
    query = urlencode(
        {
            "flow_id": str(payload.flow_id),
            "node_id": str(payload.node_id),
            "token": token,
        }
    )
    return f"{base}{_HANDLE_PATH}?{query}"
