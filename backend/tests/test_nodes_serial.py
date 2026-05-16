"""test_nodes_serial.py — hr_initial 与 hr_final 节点 interrupt + Command(resume) 行为。

用最小 StateGraph（只含一个节点）+ InMemorySaver 验证节点函数模板行为。
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from offboarding_flow.flow_engine.nodes import (
    HR_FINAL_NODE_NAME,
    HR_INITIAL_NODE_NAME,
    hr_final_node,
    hr_initial_node,
)
from offboarding_flow.flow_engine.state import OffboardingState


def _initial_state() -> dict:
    return {
        "flow_id": str(uuid.uuid4()),
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }


# ---------------------------------------------------------------------------
# hr_initial 测试
# ---------------------------------------------------------------------------
@pytest.fixture
def hr_initial_graph():
    b = StateGraph(OffboardingState)
    b.add_node(HR_INITIAL_NODE_NAME, hr_initial_node)
    b.add_edge(START, HR_INITIAL_NODE_NAME)
    b.add_edge(HR_INITIAL_NODE_NAME, END)
    return b.compile(checkpointer=InMemorySaver())


async def test_hr_initial_interrupts_for_decision(hr_initial_graph):
    state = _initial_state()
    config = {"configurable": {"thread_id": state["flow_id"]}}
    await hr_initial_graph.ainvoke(state, config=config)
    snapshot = await hr_initial_graph.aget_state(config=config)
    # interrupt 后 next 仍是该节点（等 resume）
    assert snapshot.next == (HR_INITIAL_NODE_NAME,)


async def test_hr_initial_advance_resume(hr_initial_graph):
    state = _initial_state()
    config = {"configurable": {"thread_id": state["flow_id"]}}
    await hr_initial_graph.ainvoke(state, config=config)
    final = await hr_initial_graph.ainvoke(
        Command(resume={"action": "advance", "result_text": "材料齐全", "actor": "hr.alice"}),
        config=config,
    )
    assert final["current_action"] == "advance"
    assert any(r["node_name"] == HR_INITIAL_NODE_NAME for r in final["node_results"])
    assert any(r["result_text"] == "材料齐全" for r in final["node_results"])


async def test_hr_initial_return_resume(hr_initial_graph):
    state = _initial_state()
    config = {"configurable": {"thread_id": state["flow_id"]}}
    await hr_initial_graph.ainvoke(state, config=config)
    final = await hr_initial_graph.ainvoke(
        Command(resume={"action": "return", "result_text": "材料不全", "actor": "hr.alice"}),
        config=config,
    )
    assert final["current_action"] == "return"


async def test_hr_initial_reject_resume(hr_initial_graph):
    state = _initial_state()
    config = {"configurable": {"thread_id": state["flow_id"]}}
    await hr_initial_graph.ainvoke(state, config=config)
    final = await hr_initial_graph.ainvoke(
        Command(resume={"action": "reject", "result_text": "材料造假", "actor": "hr.alice"}),
        config=config,
    )
    assert final["current_action"] == "reject"


# ---------------------------------------------------------------------------
# hr_final 测试
# ---------------------------------------------------------------------------
@pytest.fixture
def hr_final_graph():
    b = StateGraph(OffboardingState)
    b.add_node(HR_FINAL_NODE_NAME, hr_final_node)
    b.add_edge(START, HR_FINAL_NODE_NAME)
    b.add_edge(HR_FINAL_NODE_NAME, END)
    return b.compile(checkpointer=InMemorySaver())


async def test_hr_final_advance(hr_final_graph):
    state = _initial_state()
    config = {"configurable": {"thread_id": state["flow_id"]}}
    await hr_final_graph.ainvoke(state, config=config)
    final = await hr_final_graph.ainvoke(
        Command(resume={"action": "advance", "result_text": "终审通过", "actor": "hr.bob"}),
        config=config,
    )
    assert final["current_action"] == "advance"
    assert any(r["node_name"] == HR_FINAL_NODE_NAME for r in final["node_results"])


async def test_hr_final_resume_with_string_decision_falls_back(hr_final_graph):
    """resume 传非 dict 时 — defensive fallback 到 advance + result_text=str。"""
    state = _initial_state()
    config = {"configurable": {"thread_id": state["flow_id"]}}
    await hr_final_graph.ainvoke(state, config=config)
    final = await hr_final_graph.ainvoke(Command(resume="raw string"), config=config)
    assert final["current_action"] == "advance"
    assert any(r["result_text"] == "raw string" for r in final["node_results"])
