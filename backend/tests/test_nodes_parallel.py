"""test_nodes_parallel.py — 5 个并行人工节点的 interrupt + Command(resume) 行为。

用最小 StateGraph（START → node → END）+ InMemorySaver 验证 _human_node_factory
生成的节点。
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from offboarding_flow.flow_engine.nodes import PARALLEL_NODES_META
from offboarding_flow.flow_engine.state import OffboardingState


def _state() -> dict:
    return {
        "flow_id": str(uuid.uuid4()),
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }


@pytest.fixture(params=PARALLEL_NODES_META, ids=[m[0] for m in PARALLEL_NODES_META])
def parallel_node_graph(request):
    name, _title, _desc, fn = request.param
    b = StateGraph(OffboardingState)
    b.add_node(name, fn)
    b.add_edge(START, name)
    b.add_edge(name, END)
    return name, b.compile(checkpointer=InMemorySaver())


async def test_parallel_node_interrupts(parallel_node_graph):
    """每个并行节点首次进入时 interrupt，snapshot.next 仍是该节点。"""
    name, graph = parallel_node_graph
    s = _state()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph.ainvoke(s, config=cfg)
    snap = await graph.aget_state(config=cfg)
    assert snap.next == (name,)


async def test_parallel_node_advance_resumes(parallel_node_graph):
    """advance resume → node_results 含本节点 + current_action=advance。"""
    name, graph = parallel_node_graph
    s = _state()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph.ainvoke(s, config=cfg)
    final = await graph.ainvoke(
        Command(
            resume={
                "action": "advance",
                "result_text": f"{name} done",
                "actor": "tester",
            }
        ),
        config=cfg,
    )
    assert final["current_action"] == "advance"
    matched = [r for r in final["node_results"] if r["node_name"] == name]
    assert len(matched) == 1
    assert matched[0]["result_text"] == f"{name} done"
    assert matched[0]["actor"] == "tester"


async def test_parallel_node_return_resumes(parallel_node_graph):
    """return resume → current_action=return。"""
    name, graph = parallel_node_graph
    s = _state()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    await graph.ainvoke(s, config=cfg)
    final = await graph.ainvoke(
        Command(
            resume={
                "action": "return",
                "result_text": "need rework",
                "actor": "tester",
            }
        ),
        config=cfg,
    )
    assert final["current_action"] == "return"


# ---------------------------------------------------------------------------
# 元数据校验
# ---------------------------------------------------------------------------
def test_parallel_node_factory_preserves_dunder_name():
    """make_human_node 设置 _node.__name__ 便于调试 / log。"""
    for name, _title, _desc, fn in PARALLEL_NODES_META:
        assert fn.__name__ == f"{name}_node", f"{fn.__name__} != {name}_node"


def test_parallel_node_count_is_5():
    assert len(PARALLEL_NODES_META) == 5


def test_parallel_node_names_are_unique():
    names = [m[0] for m in PARALLEL_NODES_META]
    assert len(set(names)) == 5


def test_parallel_node_names_match_routes_module():
    """PARALLEL_NODES_META 名称必须匹配 routes.py 中的 PARALLEL_NODES list。"""
    from offboarding_flow.flow_engine.routes import PARALLEL_NODES as routes_parallel

    names = [m[0] for m in PARALLEL_NODES_META]
    assert sorted(names) == sorted(routes_parallel)


def test_parallel_node_titles_are_chinese():
    """所有 title 应为中文（用户面向）。"""
    expected_titles = {"设备归还", "权限回收", "知识 / 文档交接", "财务结算", "法务签字"}
    actual_titles = {m[1] for m in PARALLEL_NODES_META}
    assert actual_titles == expected_titles
