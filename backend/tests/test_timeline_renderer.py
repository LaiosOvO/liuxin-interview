"""test_timeline_renderer.py — render_timeline 纯函数单测（Phase 2 Plan 04）。"""

from __future__ import annotations

from offboarding_flow.services.timeline_renderer import (
    _format_completed_at,
    render_timeline,
)


# ---------------------------------------------------------------------------
# _format_completed_at
# ---------------------------------------------------------------------------
def test_format_completed_at_iso():
    assert _format_completed_at("2026-05-16T14:30:00+00:00") == "2026-05-16 14:30"


def test_format_completed_at_z_suffix():
    assert _format_completed_at("2026-05-16T14:30:00Z") == "2026-05-16 14:30"


def test_format_completed_at_invalid_falls_back():
    assert _format_completed_at("not-iso") == "not-iso"


def test_format_completed_at_empty():
    assert _format_completed_at("") == ""


# ---------------------------------------------------------------------------
# render_timeline
# ---------------------------------------------------------------------------
def test_render_timeline_empty():
    s = render_timeline([])
    assert "─" in s  # separator 渲染


def test_render_timeline_single_node():
    rs = [
        {
            "node_name": "apply",
            "node_title": "离职申请",
            "result_text": "个人发展",
            "actor": "zhang.san",
            "completed_at": "2026-05-16T10:00:00+00:00",
        }
    ]
    s = render_timeline(rs)
    assert "1. 离职申请" in s
    assert "zhang.san" in s
    assert "2026-05-16 10:00" in s
    assert "个人发展" in s


def test_render_timeline_multiline_result_text_indented():
    rs = [
        {
            "node_name": "device_return",
            "node_title": "设备归还",
            "result_text": "MacBook 已归还\n门禁卡 已注销\nSIM 卡 已回收",
            "actor": "it.charlie",
            "completed_at": "2026-05-16T14:50:00+00:00",
        }
    ]
    s = render_timeline(rs)
    lines = s.splitlines()
    # 3 行 result_text 都应有 4 空格缩进
    indented = [ln for ln in lines if ln.startswith("    ")]
    assert len(indented) == 3


def test_render_timeline_with_header():
    s = render_timeline([], header="【执行记录】")
    assert s.startswith("【执行记录】")


def test_render_timeline_with_action_label_advance():
    rs = [
        {
            "node_name": "manager_review",
            "node_title": "上级审批",
            "result_text": "同意",
            "actor": "li.si",
            "completed_at": "2026-05-16T11:20:00+00:00",
            "action": "advance",
        }
    ]
    s = render_timeline(rs)
    assert "✓ 继续" in s


def test_render_timeline_with_action_label_return():
    rs = [
        {
            "node_name": "hr_initial",
            "node_title": "HR 初审",
            "result_text": "材料不全",
            "actor": "hr.alice",
            "completed_at": "2026-05-16T13:00:00+00:00",
            "action": "return",
        }
    ]
    s = render_timeline(rs)
    assert "↩ 退回" in s


def test_render_timeline_with_action_label_reject():
    rs = [
        {
            "node_name": "manager_review",
            "node_title": "上级审批",
            "result_text": "不同意",
            "actor": "li.si",
            "completed_at": "2026-05-16T11:20:00+00:00",
            "action": "reject",
        }
    ]
    s = render_timeline(rs)
    assert "✗ 拒绝" in s


def test_render_timeline_full_10_nodes():
    """完整 10 节点渲染（PRD §4.5.2 示例量级）。"""
    rs = [
        {
            "node_name": f"n{i}",
            "node_title": f"节点{i}",
            "result_text": f"备注 {i}",
            "actor": f"u{i}",
            "completed_at": "2026-05-16T10:00:00+00:00",
        }
        for i in range(1, 11)
    ]
    s = render_timeline(rs, header="【执行记录】")
    assert "1. 节点1" in s
    assert "10. 节点10" in s
    # 两条分隔线（各 60 个 ─）
    assert s.count("─" * 60) == 2


def test_render_timeline_missing_optional_fields():
    """缺少 actor / completed_at 时容错（不抛异常）。"""
    rs = [{"node_name": "x", "node_title": "X 节点"}]
    s = render_timeline(rs)
    assert "X 节点" in s
    assert "unknown" in s  # 默认 actor


def test_render_timeline_empty_result_text_skips_indented_lines():
    """result_text 为空 / 全空白时不渲染缩进行。"""
    rs = [
        {
            "node_name": "x",
            "node_title": "X",
            "result_text": "",
            "actor": "u",
            "completed_at": "2026-05-16T10:00:00+00:00",
        }
    ]
    s = render_timeline(rs)
    lines = s.splitlines()
    indented = [ln for ln in lines if ln.startswith("    ")]
    assert len(indented) == 0
