"""统一响应 envelope（CONTEXT §6 + 全局 patterns.md）。

所有 API 响应必须包成 {success, data, error, meta}。
前端通过 success 判断；data 拿数据；error 拿错误消息。
"""

from __future__ import annotations

from typing import Any


def ok(data: Any = None, meta: dict | None = None) -> dict[str, Any]:
    """成功响应。返回 dict 让 FastAPI 直接序列化。"""
    return {"success": True, "data": data, "error": None, "meta": meta}


def err(message: str, meta: dict | None = None) -> dict[str, Any]:
    """失败响应。"""
    return {"success": False, "data": None, "error": message, "meta": meta}
