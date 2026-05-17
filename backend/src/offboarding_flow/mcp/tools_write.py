"""MCP write tools（MCP-03）— 4 个写工具，默认禁用，需 MCP_ALLOW_WRITE=true 启用。

三层保护（C-5 + RESEARCH Pitfall #8）：
1. 注册闸门：server.py _maybe_register_write_tools() 启动期判 env 真禁用
2. middleware 鉴权：MagicLinkAuthMiddleware on_call_tool 已 set_state user_sub/role
3. 业务闸门：每个 write tool 内调 verify_actor_can_handle(node, sub, role)

幂等（C-4 + CLAUDE.md §3.4 节点函数幂等）：
- 复用 node_service.advance / return_to_upstream / reject — 已 upsert 安全
- 接受可选 idempotency_key（UUID）— Phase 9 可加 action_logs UNIQUE 真幂等
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError

from offboarding_flow.auth.role_router import (
    PermissionDeniedError,
    verify_actor_can_handle,
)
from offboarding_flow.mcp.server import mcp
from offboarding_flow.services.ai_disclaimer import AI_DISCLAIMER
from offboarding_flow.state_store.models import FlowInstance, NodeState
from offboarding_flow.state_store.session import new_session

logger = logging.getLogger(__name__)


# AI 操作专用 disclaimer — 表明这是写入并已记录到 action_logs
_AI_WRITE_DISCLAIMER = (
    "*由 AI 操作 — 该写入已记录到 action_logs.actor 字段以便审计；"
    + AI_DISCLAIMER.removeprefix("*").removesuffix("*")
)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _audit_write(tool: str, ctx: Context | None) -> tuple[str, str]:
    """读 ctx state user_sub / user_role + 写审计日志，返回二元组。"""
    if ctx is None:
        sub: str = "unknown"
        role: str = "unknown"
    else:
        sub = (await ctx.get_state("user_sub")) or "unknown"
        role = (await ctx.get_state("user_role")) or "unknown"
    logger.warning("[mcp.write] tool=%s sub=%s role=%s", tool, sub, role)
    return sub, role


def _parse_uuid(value: str, *, field: str) -> uuid.UUID:
    """str → UUID；失败抛 ToolError。"""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as e:
        raise ToolError(f"{field} 不是合法 UUID: {value}") from e


async def _fetch_node_with_gate(
    flow_id: str,
    node_id: str,
    sub: str,
    role: str,
) -> tuple[uuid.UUID, uuid.UUID, NodeState]:
    """读节点 + 校验归属 + verify_actor_can_handle 三件套，返回 (fid, nid, node)。"""
    fid = _parse_uuid(flow_id, field="flow_id")
    nid = _parse_uuid(node_id, field="node_id")
    async with new_session() as s:
        node = await s.get(NodeState, nid)
        if node is None:
            raise ToolError(f"node_id {node_id} 未找到")
        if str(node.flow_id) != str(fid):
            raise ToolError(f"node {node_id} 不属于 flow {flow_id}")
        try:
            verify_actor_can_handle(node, sub, role)
        except PermissionDeniedError as e:
            raise ToolError(f"权限不足：{e}") from e
        # 把 ORM 实例从 session 里拷出来（detached）— session 出去就会 expire
        # 直接返回 attribute 是 OK 的因为 node 字段都是简单类型
        return fid, nid, node


def _build_idempotency_actor(sub: str, idempotency_key: str | None) -> str:
    """actor 字符串 = `mcp:<sub>`；如果有 idempotency_key 加后缀方便审计。"""
    base = f"mcp:{sub}"
    if idempotency_key:
        return f"{base}#{idempotency_key[:8]}"
    return base


# ---------------------------------------------------------------------------
# 1. advance_node — 推进节点（advance 决策）
# ---------------------------------------------------------------------------
@mcp.tool
async def advance_node(
    flow_id: str,
    node_id: str,
    result_text: str,
    idempotency_key: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """⚠️ 写操作 — 推进某节点（advance 决策）。

    权限：调用者必须是该节点的 assignee（或具备 admin role）。
    幂等：建议传 idempotency_key（UUID）— 防 LLM 多调用一次造成重复推进。

    Args:
        flow_id: 流程 UUID
        node_id: 节点 UUID
        result_text: 决策理由（写入 action_logs + node_states.result_text）
        idempotency_key: 可选 UUID，重复调用安全（action_logs UNIQUE 兜底）

    Returns:
        {"ok": true, "next_node_id": "...", "next_assignee": "...",
         "next_title": "...", "ai_disclaimer": "..."}
    """
    sub, role = await _audit_write("advance_node", ctx)
    fid, nid, _node = await _fetch_node_with_gate(flow_id, node_id, sub, role)
    return await _do_action(
        fid=fid,
        nid=nid,
        action="advance",
        result_text=result_text,
        actor=_build_idempotency_actor(sub, idempotency_key),
    )


# ---------------------------------------------------------------------------
# 2. return_node — 回退到上游
# ---------------------------------------------------------------------------
@mcp.tool
async def return_node(
    flow_id: str,
    node_id: str,
    reason: str,
    idempotency_key: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """⚠️ 写操作 — 把节点回退到上游（return 决策）。

    权限：调用者必须是该节点的 assignee（或具备 admin role）。
    幂等：建议传 idempotency_key（UUID）。

    Args:
        flow_id: 流程 UUID
        node_id: 节点 UUID
        reason: 回退原因
        idempotency_key: 可选 UUID

    Returns:
        {"ok": true, "previous_node": "...", "ai_disclaimer": "..."}
    """
    sub, role = await _audit_write("return_node", ctx)
    fid, nid, _node = await _fetch_node_with_gate(flow_id, node_id, sub, role)
    return await _do_action(
        fid=fid,
        nid=nid,
        action="return",
        result_text=reason,
        actor=_build_idempotency_actor(sub, idempotency_key),
    )


# ---------------------------------------------------------------------------
# 3. reject_node — 拒绝并终止流程
# ---------------------------------------------------------------------------
@mcp.tool
async def reject_node(
    flow_id: str,
    node_id: str,
    reason: str,
    idempotency_key: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """⚠️ 写操作 — 拒绝节点并终止流程（reject 决策，不可恢复）。

    权限：调用者必须是该节点的 assignee（或具备 admin role）。
    幂等：建议传 idempotency_key（UUID）。

    Args:
        flow_id: 流程 UUID
        node_id: 节点 UUID
        reason: 拒绝原因（强制）
        idempotency_key: 可选 UUID

    Returns:
        {"ok": true, "flow_status": "rejected", "ai_disclaimer": "..."}
    """
    sub, role = await _audit_write("reject_node", ctx)
    fid, nid, _node = await _fetch_node_with_gate(flow_id, node_id, sub, role)
    return await _do_action(
        fid=fid,
        nid=nid,
        action="reject",
        result_text=reason,
        actor=_build_idempotency_actor(sub, idempotency_key),
    )


# ---------------------------------------------------------------------------
# 4. submit_handover_doc — 提交节点交接文档
# ---------------------------------------------------------------------------
@mcp.tool
async def submit_handover_doc(
    flow_id: str,
    node_id: str,
    title: str,
    markdown: str,
    idempotency_key: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """⚠️ 写操作 — 为某节点生成 handover 文档（走 DocProvider Outline/Huly）。

    权限：调用者必须是该节点的 assignee（或具备 admin role）。
    幂等：建议传 idempotency_key（UUID）— flow.context.handover_docs 会去重。

    Args:
        flow_id: 流程 UUID
        node_id: 节点 UUID
        title: 文档标题
        markdown: 完整 markdown 内容
        idempotency_key: 可选 UUID

    Returns:
        {"ok": true, "url": "https://...", "provider": "outline|huly", "ai_disclaimer": "..."}
    """
    sub, role = await _audit_write("submit_handover_doc", ctx)
    fid, nid, node = await _fetch_node_with_gate(flow_id, node_id, sub, role)

    # 走 handover_service.generate_node_handover — 已有 fire-and-forget pattern
    async with new_session() as s:
        flow = await s.get(FlowInstance, fid)
        if flow is None:
            raise ToolError(f"flow_id {flow_id} 未找到")
        employee_id = flow.employee_id

    actor = _build_idempotency_actor(sub, idempotency_key)
    try:
        from offboarding_flow.services.handover_service import HandoverService

        svc = HandoverService()
        doc = await svc.generate_node_handover(
            flow_id=fid,
            node_id=nid,
            employee_id=employee_id,
            node_name=node.node_name,
            node_title=title,
            result_text=markdown,
            actor=actor,
            action="advance",
        )
        if doc is None:
            raise ToolError(
                "handover_service.generate_node_handover 返回 None"
                "（LLM/DocProvider 失败，请查 backend log）"
            )
        return {
            "ok": True,
            "url": doc.url,
            "title": doc.title,
            "provider": doc.provider,
            "ai_disclaimer": _AI_WRITE_DISCLAIMER,
        }
    except ImportError as e:
        raise ToolError(f"handover_service 不可用: {e}") from e


# ---------------------------------------------------------------------------
# 内部 — 复用 NodeService.submit_action
# ---------------------------------------------------------------------------


async def _do_action(
    *,
    fid: uuid.UUID,
    nid: uuid.UUID,
    action: str,
    result_text: str,
    actor: str,
) -> dict[str, Any]:
    """复用 node_service.submit_action（已 upsert + 双写规范）。

    返回成功 dict（含 ai_disclaimer）；任何业务侧 HTTPException 转 ToolError。
    """
    from fastapi import HTTPException

    from offboarding_flow.services import NodeService
    from offboarding_flow.state_store.repositories import (
        ActionRepository,
        FlowRepository,
        NodeRepository,
    )

    async with new_session() as session:
        # 装配 NodeService（复用业务双写规范 — graph 推进会走 LangGraph）
        flow_repo = FlowRepository(session)
        node_repo = NodeRepository(session)
        action_repo = ActionRepository(session)

        # 拿 compiled graph — 已在 lifespan build_graph 注册全局；测试环境会 monkeypatch
        try:
            from offboarding_flow.flow_engine.graph import get_graph

            graph = get_graph()
        except Exception as e:
            raise ToolError(f"flow graph 未初始化: {e}") from e

        svc = NodeService(
            session=session,
            flow_repo=flow_repo,
            node_repo=node_repo,
            action_repo=action_repo,
            graph=graph,
        )
        try:
            result = await svc.submit_action(
                flow_id=fid,
                node_id=nid,
                action=action,
                result_text=result_text,
                actor=actor,
            )
        except HTTPException as e:
            raise ToolError(f"业务校验失败: {e.detail}") from e
        return {
            "ok": True,
            "action": action,
            "result": result,
            "ai_disclaimer": _AI_WRITE_DISCLAIMER,
        }


__all__ = [
    "advance_node",
    "reject_node",
    "return_node",
    "submit_handover_doc",
]
