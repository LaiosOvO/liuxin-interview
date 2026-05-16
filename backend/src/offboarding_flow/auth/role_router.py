"""角色 → 前端 redirect 路径解析（CONTEXT §D9）。

Phase 3 仅返回 URL 字符串；Phase 5 落地真实前端页面。
未知 role 用默认 applicant 视图（safest fallback）。
"""

from __future__ import annotations

from uuid import UUID

# 前端已落地路由（Phase 5）：
# - applicant → /my/flows （个人视角，会查所有流程）
# - 其他角色 → /flow/[flow_id]/node/[node_id] （通用节点处理页）
_PATHS: dict[str, str] = {
    "applicant": "/my/flows",
    "manager": "/flow/{flow_id}/node/{node_id}/",
    "hr": "/flow/{flow_id}/node/{node_id}/",
    "it_admin": "/flow/{flow_id}/node/{node_id}/",
    "finance": "/flow/{flow_id}/node/{node_id}/",
    "legal": "/flow/{flow_id}/node/{node_id}/",
    "kb_owner": "/flow/{flow_id}/node/{node_id}/",
    "archivist": "/flow/{flow_id}/node/{node_id}/",
}


def resolve_redirect(role: str, flow_id: UUID, node_id: UUID) -> str:
    """根据 role 返回对应前端路径。未知 role 用默认 applicant 视图。"""
    template = _PATHS.get(role, _PATHS["applicant"])
    return template.format(flow_id=flow_id, node_id=node_id)
