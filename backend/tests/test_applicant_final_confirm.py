"""test_applicant_final_confirm.py — 申请人最终确认节点（DF-02 ★★★★★）。

测试矩阵：
- advance / return 两态决策
- reject 防御性回退（PRD §4.5.2 申请人节点无 reject）
- 默认 actor = 申请人 username
- 默认 result_text 视 action 而定
- timeline 注入 interrupt payload
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from offboarding_flow.flow_engine.nodes.applicant_final_confirm import (
    APPLICANT_FINAL_CONFIRM_NODE_NAME,
    applicant_final_confirm_node,
)
from offboarding_flow.flow_engine.state import OffboardingState


@pytest.fixture
def graph_with_seeded_results():
    b = StateGraph(OffboardingState)
    b.add_node(APPLICANT_FINAL_CONFIRM_NODE_NAME, applicant_final_confirm_node)
    b.add_edge(START, APPLICANT_FINAL_CONFIRM_NODE_NAME)
    b.add_edge(APPLICANT_FINAL_CONFIRM_NODE_NAME, END)
    return b.compile(checkpointer=InMemorySaver())


def _state_with_9_results() -> dict:
    return {
        "flow_id": str(uuid.uuid4()),
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [
            {
                "node_name": f"n{i}",
                "node_title": f"节点{i}",
                "result_text": f"备注{i}",
                "actor": "u",
                "completed_at": "2026-05-16T10:00:00+00:00",
            }
            for i in range(1, 10)
        ],
        "context": {},
    }


async def test_advance_resume(graph_with_seeded_results):
    """advance → node_results 长度 = 9 seed + 1 applicant = 10。"""
    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(
            resume={
                "action": "advance",
                "result_text": "无异议",
                "actor": "zhang.san",
            }
        ),
        config=cfg,
    )
    assert final["current_action"] == "advance"
    assert len(final["node_results"]) == 10
    assert final["node_results"][-1]["node_name"] == APPLICANT_FINAL_CONFIRM_NODE_NAME


async def test_return_resume(graph_with_seeded_results):
    """return → current_action=return。"""
    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(
            resume={
                "action": "return",
                "result_text": "我对第 4 步有异议",
                "actor": "zhang.san",
            }
        ),
        config=cfg,
    )
    assert final["current_action"] == "return"


async def test_reject_falls_back_to_advance(graph_with_seeded_results):
    """申请人节点无 reject — 防御性回退到 advance（PRD §4.5.2）。"""
    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(resume={"action": "reject", "result_text": "x", "actor": "zhang.san"}),
        config=cfg,
    )
    assert final["current_action"] == "advance"  # reject 被 sanitize


async def test_default_actor_is_employee_id(graph_with_seeded_results):
    """resume 不传 actor → 默认用 state.employee_id。"""
    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(resume={"action": "advance", "result_text": "ok"}),
        config=cfg,
    )
    applicant_result = final["node_results"][-1]
    assert applicant_result["actor"] == "zhang.san"


async def test_default_result_text_for_advance(graph_with_seeded_results):
    """resume 不传 result_text + action=advance → 默认 '无异议，已确认'。"""
    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(resume={"action": "advance", "actor": "zhang.san"}),
        config=cfg,
    )
    assert final["node_results"][-1]["result_text"] == "无异议，已确认"


async def test_default_result_text_for_return(graph_with_seeded_results):
    """resume 不传 result_text + action=return → 默认 '有异议，退回 HR 终审'。"""
    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(resume={"action": "return", "actor": "zhang.san"}),
        config=cfg,
    )
    assert final["node_results"][-1]["result_text"] == "有异议，退回 HR 终审"


async def test_completed_at_iso_format(graph_with_seeded_results):
    """默认 completed_at 是 ISO 8601 含时区。"""
    from datetime import datetime

    s = _state_with_9_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph_with_seeded_results.ainvoke(s, config=cfg)
    final = await graph_with_seeded_results.ainvoke(
        Command(resume={"action": "advance", "actor": "zhang.san"}),
        config=cfg,
    )
    completed = final["node_results"][-1]["completed_at"]
    dt = datetime.fromisoformat(completed)
    assert dt.tzinfo is not None
