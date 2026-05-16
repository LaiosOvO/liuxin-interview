"""timeline_renderer — 把 state.node_results 渲染为人类可读时间线文本。

用途（PRD §4.5.2 + §4.5.3）：
- applicant_final_confirm interrupt payload（前端展示）
- Phase 4 申请人确认邮件正文（HTML / 纯文本两版）
- Plan 06 E2E 测试断言

纯函数 — 不接 DB / 不接 graph。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_ACTION_LABEL: dict[str, str] = {
    "advance": "✓ 继续",
    "return": "↩ 退回",
    "reject": "✗ 拒绝",
}


def _format_completed_at(iso: str) -> str:
    """ISO 8601 → 'YYYY-MM-DD HH:MM'。容错（不是有效 ISO 时直接返回原值）。"""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso


def render_timeline(
    node_results: list[dict[str, Any]],
    header: str | None = None,
    include_separator: bool = True,
) -> str:
    """渲染时间线为多行文本（PRD §4.5.2 邮件示例格式）。

    Args:
        node_results: list of {node_name, node_title, result_text, actor, completed_at, action?}
        header: 可选首行标题（如 "【执行记录】"）
        include_separator: 是否在头尾加分隔线

    Returns:
        多行字符串，每个 node 一段：
            1. 节点标题  (actor, YYYY-MM-DD HH:MM)  ✓ 继续
                节点详情第 1 行
                节点详情第 2 行
    """
    lines: list[str] = []
    if header:
        lines.append(header)
    if include_separator:
        lines.append("─" * 60)

    for idx, r in enumerate(node_results, start=1):
        title = r.get("node_title") or r.get("node_name", "?")
        actor = r.get("actor", "unknown")
        completed = _format_completed_at(r.get("completed_at", ""))
        action_label = _ACTION_LABEL.get(r.get("action", ""), "").strip()

        first_line = f"{idx}. {title:<14}  ({actor}, {completed})"
        if action_label:
            first_line += f"  {action_label}"
        lines.append(first_line)

        result_text = (r.get("result_text") or "").strip()
        if result_text:
            # 缩进 4 空格，自然多行支持
            for rt_line in result_text.splitlines():
                lines.append(f"    {rt_line}")

    if include_separator:
        lines.append("─" * 60)
    return "\n".join(lines)
