"""角色 → 前端 redirect 路径解析（CONTEXT §D9）+ 节点-actor 闸门（C-5）。

Phase 3 仅返回 URL 字符串；Phase 5 落地真实前端页面。
未知 role 用默认 applicant 视图（safest fallback）。

Phase 8 / Plan 07 — verify_actor_can_handle：
- 给 MCP write tools 用：决定当前 actor (sub / role) 是否能操作某节点
- 规则：sub == node.assignee 或 role == admin → 允许；否则抛 PermissionDeniedError
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from offboarding_flow.state_store.models import NodeState

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


# 受信任的"超级角色"— 跳过 assignee 校验（admin / stdio 本地）
_TRUSTED_ROLES: frozenset[str] = frozenset({"admin"})


class PermissionDeniedError(Exception):
    """actor 无权操作该节点（不是 assignee 且非 trusted role）。"""

    def __init__(
        self,
        *,
        actor_sub: str,
        actor_role: str,
        node_name: str,
        assignee: str | None,
    ) -> None:
        self.actor_sub = actor_sub
        self.actor_role = actor_role
        self.node_name = node_name
        self.assignee = assignee
        super().__init__(
            f"actor sub={actor_sub} role={actor_role} 不能操作节点 "
            f"{node_name}（assignee={assignee}）"
        )


def resolve_redirect(role: str, flow_id: UUID, node_id: UUID) -> str:
    """根据 role 返回对应前端路径。未知 role 用默认 applicant 视图。"""
    template = _PATHS.get(role, _PATHS["applicant"])
    return template.format(flow_id=flow_id, node_id=node_id)


def verify_actor_can_handle(
    node: "NodeState",
    actor_sub: str,
    actor_role: str,
) -> None:
    """校验 actor (sub / role) 是否能操作该节点（MCP write tools 闸门，C-5）。

    放行条件（满足任一）：
    - actor_role 在 _TRUSTED_ROLES（admin / stdio 本地）
    - actor_sub == node.assignee

    Args:
        node: 业务表 NodeState ORM 实例
        actor_sub: 当前调用者 username（从 JWT payload.sub 拿）
        actor_role: 当前调用者角色（从 JWT payload.role 拿）

    Raises:
        PermissionDeniedError: actor 不是 assignee 且非 trusted role
    """
    if actor_role in _TRUSTED_ROLES:
        return
    if node.assignee and actor_sub == node.assignee:
        return
    raise PermissionDeniedError(
        actor_sub=actor_sub,
        actor_role=actor_role,
        node_name=node.node_name,
        assignee=node.assignee,
    )


__all__ = [
    "PermissionDeniedError",
    "resolve_redirect",
    "verify_actor_can_handle",
]
