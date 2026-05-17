"""MCP read tools（MCP-02）— 7 个只读工具，默认全开。

约定（CLAUDE.md §3.3 双层状态分离 + PRD §15.3 AI 边界）：
- 全部走业务表（`app.*`），不读 LangGraph checkpoint
- 每个 tool 顶部 log `[mcp] tool=X sub=X role=X`（who-queried-what 审计）
- AI 生成内容必须带 ai_disclaimer
- docstring 是给 LLM 看的描述 — 必须中文 + 返回结构示例

注意：
- import 本模块即触发 @mcp.tool 注册到 server.mcp 实例
- 所以 server.py 在 add_middleware 之后必须 `from offboarding_flow.mcp import tools_read`
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from offboarding_flow.mcp.server import mcp
from offboarding_flow.services.ai_disclaimer import AI_DISCLAIMER
from offboarding_flow.state_store.enums import FlowStatus, NodeStatus
from offboarding_flow.state_store.models import (
    ActionLog,
    FlowInstance,
    NodeState,
)
from offboarding_flow.state_store.session import new_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _audit(tool: str, ctx: Context | None) -> tuple[str, str]:
    """读 ctx state user_sub / user_role + 写审计日志，返回二元组。

    Context.get_state 是 async — 必须 await。"""
    if ctx is None:
        sub: str = "unknown"
        role: str = "unknown"
    else:
        sub = (await ctx.get_state("user_sub")) or "unknown"
        role = (await ctx.get_state("user_role")) or "unknown"
    logger.info("[mcp] tool=%s sub=%s role=%s", tool, sub, role)
    return sub, role


def _parse_uuid(value: str, *, field: str) -> uuid.UUID:
    """把 str → UUID；失败抛 ToolError 不暴露原始异常。"""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as e:
        raise ToolError(f"{field} 不是合法 UUID: {value}") from e


def _flow_to_dict(flow: FlowInstance, nodes: list[NodeState]) -> dict[str, Any]:
    """FlowInstance ORM → 可 JSON 序列化 dict（含当前节点摘要）。"""
    current = next(
        (n for n in nodes if n.status == NodeStatus.WAITING_HUMAN.value),
        None,
    )
    return {
        "flow_id": str(flow.id),
        "employee_id": flow.employee_id,
        "template": flow.template,
        "status": flow.status,
        "started_at": flow.started_at.isoformat() if flow.started_at else None,
        "completed_at": flow.completed_at.isoformat() if flow.completed_at else None,
        "node_count": len(nodes),
        "current_node": (
            {
                "id": str(current.id),
                "name": current.node_name,
                "title": current.node_title,
                "assignee": current.assignee,
            }
            if current is not None
            else None
        ),
    }


def _node_to_dict(node: NodeState) -> dict[str, Any]:
    """NodeState ORM → dict。"""
    return {
        "id": str(node.id),
        "name": node.node_name,
        "title": node.node_title,
        "status": node.status,
        "assignee": node.assignee,
        "result_text": node.result_text,
        "is_overdue": node.is_overdue,
        "entered_at": node.entered_at.isoformat() if node.entered_at else None,
        "completed_at": node.completed_at.isoformat() if node.completed_at else None,
    }


def _render_dag_markdown(nodes: list[NodeState]) -> str:
    """把节点列表渲染成简单的 DAG markdown（给 LLM 看的进度概览）。"""
    if not nodes:
        return "_（流程暂无节点）_"
    lines: list[str] = []
    lines.append("```mermaid")
    lines.append("graph TD")
    for i, n in enumerate(nodes):
        marker = {
            "done": "✅",
            "rejected": "❌",
            "returned": "↩️",
            "waiting_human": "⏳",
            "in_review": "🔍",
            "pending": "·",
        }.get(n.status, "·")
        safe_id = f"N{i}"
        label = f"{marker} {n.node_title}".replace('"', "'")
        lines.append(f'  {safe_id}["{label}"]')
        if i > 0:
            lines.append(f"  N{i - 1} --> N{i}")
    lines.append("```")
    lines.append("")
    lines.append("| # | 节点 | 状态 | assignee | 完成时间 |")
    lines.append("|---|------|------|----------|----------|")
    for i, n in enumerate(nodes, 1):
        ts = (n.completed_at.isoformat()[:16].replace("T", " ")) if n.completed_at else "—"
        lines.append(f"| {i} | {n.node_title} | `{n.status}` | " f"{n.assignee or '—'} | {ts} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. list_flows
# ---------------------------------------------------------------------------
@mcp.tool
async def list_flows(
    filter: str = "active",
    limit: int = 50,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """列出所有离职流程（active / completed / rejected / all）。

    Args:
        filter: active | completed | rejected | all（默认 active）
        limit: 最多返回多少条（默认 50）

    Returns:
        {"flows": [{flow_id, employee_id, status, current_node, ...}], "total": N}
    """
    await _audit("list_flows", ctx)
    status_map = {
        "active": FlowStatus.IN_PROGRESS.value,
        "completed": FlowStatus.COMPLETED.value,
        "rejected": FlowStatus.REJECTED.value,
    }
    async with new_session() as s:
        stmt = select(FlowInstance).order_by(FlowInstance.started_at.desc()).limit(limit)
        if filter != "all":
            target = status_map.get(filter)
            if target is None:
                raise ToolError(f"filter 必须是 active/completed/rejected/all，收到: {filter}")
            stmt = stmt.where(FlowInstance.status == target)
        rows = (await s.execute(stmt)).scalars().all()
        result: list[dict[str, Any]] = []
        for flow in rows:
            nodes_stmt = (
                select(NodeState).where(NodeState.flow_id == flow.id).order_by(NodeState.created_at)
            )
            nodes = list((await s.execute(nodes_stmt)).scalars().all())
            result.append(_flow_to_dict(flow, nodes))
        return {"flows": result, "total": len(result)}


# ---------------------------------------------------------------------------
# 2. get_flow
# ---------------------------------------------------------------------------
@mcp.tool
async def get_flow(flow_id: str, ctx: Context | None = None) -> dict[str, Any]:
    """获取指定流程的 DAG 状态 + 节点清单 + 进度（含 mermaid + 表格）。

    Args:
        flow_id: 流程 UUID

    Returns:
        {"flow": {...}, "nodes": [...], "current_node": {...}|None, "dag_markdown": "..."}
    """
    await _audit("get_flow", ctx)
    fid = _parse_uuid(flow_id, field="flow_id")
    async with new_session() as s:
        flow = await s.get(FlowInstance, fid)
        if flow is None:
            raise ToolError(f"flow_id {flow_id} 未找到")
        nodes_stmt = (
            select(NodeState).where(NodeState.flow_id == fid).order_by(NodeState.created_at)
        )
        nodes = list((await s.execute(nodes_stmt)).scalars().all())
        return {
            "flow": _flow_to_dict(flow, nodes),
            "nodes": [_node_to_dict(n) for n in nodes],
            "current_node": next(
                (_node_to_dict(n) for n in nodes if n.status == NodeStatus.WAITING_HUMAN.value),
                None,
            ),
            "dag_markdown": _render_dag_markdown(nodes),
        }


# ---------------------------------------------------------------------------
# 3. get_node_form
# ---------------------------------------------------------------------------
@mcp.tool
async def get_node_form(
    flow_id: str,
    node_id: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """获取某节点的表单（节点说明 / 当前 payload / 已填 result_text / 当前 assignee）。

    Args:
        flow_id: 流程 UUID
        node_id: 节点 UUID

    Returns:
        {"node": {...}, "payload": {...}, "result_text": "..." | None,
         "assignee": "...", "role": "..."}
    """
    sub, _role = await _audit("get_node_form", ctx)
    fid = _parse_uuid(flow_id, field="flow_id")
    nid = _parse_uuid(node_id, field="node_id")
    async with new_session() as s:
        node = await s.get(NodeState, nid)
        if node is None:
            raise ToolError(f"node_id {node_id} 未找到")
        if str(node.flow_id) != str(fid):
            raise ToolError(f"node {node_id} 不属于 flow {flow_id}")
        flow = await s.get(FlowInstance, fid)
        ctx_data = (flow.context or {}) if flow is not None else {}
        return {
            "node": _node_to_dict(node),
            "payload": ctx_data,
            "result_text": node.result_text,
            "assignee": node.assignee,
            "role": _role,
            "querier_sub": sub,
        }


# ---------------------------------------------------------------------------
# 4. get_user_assignments
# ---------------------------------------------------------------------------
@mcp.tool
async def get_user_assignments(
    username: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """列出某用户当前待处理的节点（跨所有 active 流程）。

    Args:
        username: 要查询的用户名（如 'hr.alice'）

    Returns:
        {"assignments": [{flow_id, node_id, title, urgency, started_at}], "total": N}
    """
    await _audit("get_user_assignments", ctx)
    if not username:
        raise ToolError("username 不能为空")
    async with new_session() as s:
        stmt = (
            select(NodeState, FlowInstance)
            .join(FlowInstance, NodeState.flow_id == FlowInstance.id)
            .where(NodeState.assignee == username)
            .where(NodeState.status == NodeStatus.WAITING_HUMAN.value)
            .order_by(NodeState.entered_at.asc())
        )
        rows = (await s.execute(stmt)).all()
        assignments: list[dict[str, Any]] = []
        for node, flow in rows:
            assignments.append(
                {
                    "flow_id": str(flow.id),
                    "employee_id": flow.employee_id,
                    "node_id": str(node.id),
                    "title": node.node_title,
                    "urgency": "overdue" if node.is_overdue else "normal",
                    "started_at": (node.entered_at.isoformat() if node.entered_at else None),
                }
            )
        return {"assignments": assignments, "total": len(assignments)}


# ---------------------------------------------------------------------------
# 5. get_handover_docs
# ---------------------------------------------------------------------------
@mcp.tool
async def get_handover_docs(
    flow_id: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """列出某流程已生成的 handover docs（每节点一份小报告）。

    Args:
        flow_id: 流程 UUID

    Returns:
        {"docs": [{node_name, node_title, url, title, provider}], "total": N}
    """
    await _audit("get_handover_docs", ctx)
    fid = _parse_uuid(flow_id, field="flow_id")
    async with new_session() as s:
        flow = await s.get(FlowInstance, fid)
        if flow is None:
            raise ToolError(f"flow_id {flow_id} 未找到")
        docs = list((flow.context or {}).get("handover_docs", []))
        return {"docs": docs, "total": len(docs)}


# ---------------------------------------------------------------------------
# 6. get_final_summary
# ---------------------------------------------------------------------------
@mcp.tool
async def get_final_summary(
    flow_id: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """获取某流程的最终聚合总报告（GLM 生成的 markdown，由 archive 节点触发生成）。

    Args:
        flow_id: 流程 UUID

    Returns:
        {"summary_markdown": "...", "doc": {url, title, provider} | None,
         "ai_disclaimer": "*由 AI 生成 — ...*"}
    """
    await _audit("get_final_summary", ctx)
    fid = _parse_uuid(flow_id, field="flow_id")
    async with new_session() as s:
        flow = await s.get(FlowInstance, fid)
        if flow is None:
            raise ToolError(f"flow_id {flow_id} 未找到")
        ctx_data = flow.context or {}
        doc = ctx_data.get("final_summary_doc")
        node_results = list(ctx_data.get("node_results", []))
        # 摘要 markdown — 简单列出节点结果（真正的 GLM markdown 在 final_summary_doc.url 里）
        if node_results:
            lines: list[str] = [f"# 离职流程总结 — {flow.employee_id}", ""]
            lines.append(f"- **流程状态**：{flow.status}")
            lines.append(f"- **节点数**：{len(node_results)}")
            lines.append("")
            lines.append("## 节点完成清单")
            for r in node_results:
                lines.append(
                    f"- **{r.get('node_title', r.get('node_name', '?'))}**："
                    f"@{r.get('actor', '?')} → `{r.get('action', '?')}` "
                    f"({(r.get('result_text', '') or '')[:80]})"
                )
            summary_markdown = "\n".join(lines)
        else:
            summary_markdown = (
                f"# 离职流程总结 — {flow.employee_id}\n\n_（流程未推进，暂无节点结果）_"
            )
        return {
            "summary_markdown": summary_markdown,
            "doc": doc,
            "ai_disclaimer": AI_DISCLAIMER,
        }


# ---------------------------------------------------------------------------
# 7. get_meeting_summary
# ---------------------------------------------------------------------------
@mcp.tool
async def get_meeting_summary(
    meeting_id: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """获取某会议纪要的 AI 分析（tasks/blockers/decisions）。

    Args:
        meeting_id: 会议 ID（当前项目未持久化 meetings 表，meeting_id 暂为
            action_logs 中 payload.meeting_id 的标识；若无则返回空结构）

    Returns:
        {"meeting_id": "...", "tasks": [], "blockers": [], "decisions": [],
         "ai_disclaimer": "*由 AI 生成 — ...*", "note": "..."}
    """
    await _audit("get_meeting_summary", ctx)
    if not meeting_id:
        raise ToolError("meeting_id 不能为空")
    # 当前项目未持久化 meetings 表（meeting_service 是 transient
    # raw_text → LLM → Outline + MM），所以这里返回空结构 + note 说明
    async with new_session() as s:
        stmt = (
            select(ActionLog)
            .where(ActionLog.payload.op("->>")("meeting_id") == meeting_id)
            .order_by(ActionLog.created_at.desc())
            .limit(1)
        )
        row = (await s.execute(stmt)).scalar_one_or_none()
        if row is not None and row.payload:
            payload = row.payload
            return {
                "meeting_id": meeting_id,
                "tasks": payload.get("tasks", []),
                "blockers": payload.get("blockers", []),
                "decisions": payload.get("decisions", []),
                "ai_disclaimer": AI_DISCLAIMER,
                "note": "from action_logs payload",
            }
        return {
            "meeting_id": meeting_id,
            "tasks": [],
            "blockers": [],
            "decisions": [],
            "ai_disclaimer": AI_DISCLAIMER,
            "note": "项目未持久化 meetings 表；如需查会议纪要请去 Outline / Huly 文档库",
        }


__all__ = [
    "get_final_summary",
    "get_flow",
    "get_handover_docs",
    "get_meeting_summary",
    "get_node_form",
    "get_user_assignments",
    "list_flows",
]
