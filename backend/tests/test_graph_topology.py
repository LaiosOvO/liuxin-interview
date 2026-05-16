"""test_graph_topology.py — 校验 graph 拓扑结构（Phase 2 + Phase 4.5）。

Phase 4.5 变化（PRD §18）：节点数 10 → 11（新增 auto_archive_to_storage 自动节点）；
applicant_final_confirm advance 不再直接到 archive，先到 auto_archive_to_storage。
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START

from offboarding_flow.flow_engine.graph import _build_state_graph
from offboarding_flow.flow_engine.nodes import (
    APPLICANT_FINAL_CONFIRM_NODE_NAME,
    APPLY_NODE_NAME,
    ARCHIVE_NODE_NAME,
    AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
    HR_FINAL_NODE_NAME,
    HR_INITIAL_NODE_NAME,
    MANAGER_REVIEW_NODE_NAME,
    PARALLEL_NODES_META,
)

EXPECTED_NODES = {
    APPLY_NODE_NAME,
    MANAGER_REVIEW_NODE_NAME,
    HR_INITIAL_NODE_NAME,
    HR_FINAL_NODE_NAME,
    APPLICANT_FINAL_CONFIRM_NODE_NAME,
    AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,  # Phase 4.5（PRD §18）
    ARCHIVE_NODE_NAME,
    *[m[0] for m in PARALLEL_NODES_META],
}


@pytest.fixture
def builder():
    return _build_state_graph()


def test_graph_has_12_nodes(builder):
    """12 节点全部注册（7 单线 + 5 并行 = 12；Phase 4.5 加 auto_archive_to_storage）。"""
    node_names = set(builder.nodes.keys())
    assert (
        node_names == EXPECTED_NODES
    ), f"expected {sorted(EXPECTED_NODES)}, got {sorted(node_names)}"


def test_parallel_nodes_registered(builder):
    """5 并行节点全部注册。"""
    parallel_names = [m[0] for m in PARALLEL_NODES_META]
    assert len(parallel_names) == 5
    for name in parallel_names:
        assert name in builder.nodes


def test_graph_compiles_with_in_memory_saver():
    """graph 编译不抛错。"""
    builder = _build_state_graph()
    graph = builder.compile(checkpointer=InMemorySaver())
    assert graph is not None


def test_graph_archive_edges_to_end(builder):
    """archive → END 直接边。"""
    edges = list(builder.edges)
    assert any(
        f == ARCHIVE_NODE_NAME and t == END for f, t in edges
    ), f"archive → END 缺失，edges={edges}"


def test_graph_start_edges_to_apply(builder):
    """START → apply。"""
    edges = list(builder.edges)
    assert any(
        f == START and t == APPLY_NODE_NAME for f, t in edges
    ), f"START → apply 缺失，edges={edges}"


def test_graph_apply_edges_to_manager_review(builder):
    """apply → manager_review。"""
    edges = list(builder.edges)
    assert any(f == APPLY_NODE_NAME and t == MANAGER_REVIEW_NODE_NAME for f, t in edges)


def test_all_parallel_nodes_edge_to_hr_final(builder):
    """5 并行节点全部直接 add_edge 到 hr_final（fan-in）。"""
    edges = list(builder.edges)
    for name, *_ in PARALLEL_NODES_META:
        assert any(
            f == name and t == HR_FINAL_NODE_NAME for f, t in edges
        ), f"{name} → hr_final 边缺失"


def test_graph_node_count_matches_expected():
    """11 节点：7 串行 + 5 并行 - 1 重叠 = 11（Phase 4.5 加分项 PRD §18）。

    7 串行 = apply / manager_review / hr_initial / hr_final / applicant / auto_archive_to_storage / archive
    5 并行 = device_return / access_revoke / knowledge_handover / finance_settle / legal_sign
    重叠为 0 → 总 12 ... 等等 7 + 5 = 12？再算：
    serial = apply, manager_review, hr_initial, hr_final, applicant, auto_archive, archive = 7
    parallel = 5
    total = 12 nodes
    """
    expected_count = 7 + 5  # 12 节点（Phase 4.5 加 auto_archive_to_storage）
    assert len(EXPECTED_NODES) == expected_count, f"EXPECTED_NODES 实际 {len(EXPECTED_NODES)} 节点"


def test_graph_auto_archive_edges_to_archive(builder):
    """Phase 4.5：auto_archive_to_storage → archive 直接边。"""
    edges = list(builder.edges)
    assert any(
        f == AUTO_ARCHIVE_TO_STORAGE_NODE_NAME and t == ARCHIVE_NODE_NAME for f, t in edges
    ), f"auto_archive_to_storage → archive 缺失，edges={edges}"


def test_graph_applicant_no_longer_directly_to_archive(builder):
    """Phase 4.5：applicant_final_confirm 不再直接 add_edge 到 archive（中间插了 auto_archive_to_storage）。

    注意：add_conditional_edges 不会出现在 .edges；本测试只校验「无条件 add_edge」级别
    确实没有 applicant → archive。
    """
    edges = list(builder.edges)
    direct = [
        (f, t)
        for f, t in edges
        if f == APPLICANT_FINAL_CONFIRM_NODE_NAME and t == ARCHIVE_NODE_NAME
    ]
    assert direct == [], f"applicant → archive 直接边应已移除 (中间插 auto_archive)，实际={direct}"


async def test_graph_runs_apply_then_interrupts_at_manager_review():
    """启动流程后跑过 apply 自动 → manager_review interrupt。"""
    import uuid

    from offboarding_flow.flow_engine.state import OffboardingState

    builder = _build_state_graph()
    graph = builder.compile(checkpointer=InMemorySaver())
    flow_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": flow_id}}
    initial: OffboardingState = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }
    await graph.ainvoke(initial, config=cfg)
    snap = await graph.aget_state(config=cfg)
    # interrupt 在 manager_review，next 应是 manager_review
    assert snap.next == (MANAGER_REVIEW_NODE_NAME,)
