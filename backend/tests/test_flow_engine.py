"""LangGraph 引擎单元测试 — 用 InMemorySaver 不依赖真 postgres。

覆盖：
- OffboardingState 含 Annotated reducer（PITFALLS #4 防 last-write-wins）
- graph 可构建 + compile
- 起流程 → apply 自动跑 → manager_review interrupt 挂起
- Command(resume) 唤醒后 graph 推进到 END
- node_results reducer 累计两个节点的结果
- reject 路径
- 重启 graph 后从 checkpoint 恢复（同 thread_id 可继续）
"""

import uuid
from operator import add
from typing import get_origin, get_type_hints

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from offboarding_flow.flow_engine.graph import _build_state_graph, dispose_graph
from offboarding_flow.flow_engine.state import OffboardingState


# ---------------------------------------------------------------------------
# 静态校验：state schema
# ---------------------------------------------------------------------------
def test_state_node_results_uses_add_reducer():
    """OffboardingState.node_results 必须用 Annotated + operator.add reducer。

    漏 reducer 会导致并行 fan-out（Phase 2）last-write-wins 静默丢数据 — PITFALLS #4。
    """
    # get_type_hints 含 include_extras=True 才能拿到 Annotated 的 metadata
    hints = get_type_hints(OffboardingState, include_extras=True)
    nr = hints["node_results"]
    # Annotated[list[...], add] → __metadata__ 含 add
    assert hasattr(nr, "__metadata__"), f"node_results 必须是 Annotated: {nr}"
    assert add in nr.__metadata__, f"reducer 必须是 operator.add: {nr.__metadata__}"
    # 校验内部类型是 list[NodeResult]
    origin = get_origin(nr.__origin__)
    assert origin is list, f"node_results 内部类型必须是 list: {origin}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
async def _reset_graph_singleton():
    """每个测试前后重置 graph 单例。"""
    await dispose_graph()
    yield
    await dispose_graph()


@pytest.fixture
def saver():
    return InMemorySaver()


@pytest.fixture
def compiled_graph(saver):
    builder = _build_state_graph()
    return builder.compile(checkpointer=saver)


# ---------------------------------------------------------------------------
# 集成测试：graph 流转
# ---------------------------------------------------------------------------
async def test_graph_runs_apply_then_interrupts_at_manager_review(compiled_graph):
    """起流程 → apply 自动跑完 → manager_review 触发 interrupt。"""
    flow_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": flow_id}}

    initial_state: OffboardingState = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }

    # 首次 invoke — 期望在 manager_review interrupt
    result = await compiled_graph.ainvoke(initial_state, config=config)

    # 校验：apply 已跑完（node_results 含 apply 一项），manager_review 已 interrupt
    assert len(result["node_results"]) == 1
    assert result["node_results"][0]["node_name"] == "apply"
    # interrupt 数据通过 __interrupt__ 暴露
    assert "__interrupt__" in result
    interrupts = result["__interrupt__"]
    assert any(intr.value.get("node_name") == "manager_review" for intr in interrupts)


async def test_command_resume_advances_to_end(compiled_graph):
    """interrupt 后用 Command(resume) 唤醒，graph 推进到 END，node_results 累计 2 项。"""
    flow_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": flow_id}}

    initial_state: OffboardingState = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }

    # 第一阶段：跑到 manager_review 挂起
    await compiled_graph.ainvoke(initial_state, config=config)

    # 第二阶段：用 Command(resume) 唤醒
    resume_payload = {
        "action": "advance",
        "result_text": "同意离职",
        "actor": "li.si",
    }
    final = await compiled_graph.ainvoke(Command(resume=resume_payload), config=config)

    # 校验：node_results 含 apply + manager_review 两项（reducer 工作正常）
    names = [r["node_name"] for r in final["node_results"]]
    assert names == ["apply", "manager_review"], f"Expected [apply, manager_review], got {names}"
    assert final["current_action"] == "advance"
    assert final["node_results"][1]["result_text"] == "同意离职"
    assert final["node_results"][1]["actor"] == "li.si"


async def test_reject_terminates_flow(compiled_graph):
    """manager_review reject 三态决策路由到 END。"""
    flow_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": flow_id}}

    initial_state: OffboardingState = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }

    await compiled_graph.ainvoke(initial_state, config=config)

    reject_payload = {
        "action": "reject",
        "result_text": "条件不符",
        "actor": "li.si",
    }
    final = await compiled_graph.ainvoke(Command(resume=reject_payload), config=config)

    # 校验：current_action=reject + 流程已结束 + reject 记录在 manager_review
    assert final["current_action"] == "reject"
    mr = next(r for r in final["node_results"] if r["node_name"] == "manager_review")
    assert mr["result_text"] == "条件不符"


async def test_checkpoint_recovers_from_interrupt(saver):
    """模拟"进程重启"：重新构建 graph 但用同一 saver，能从 checkpoint 恢复。

    Phase 1 验收 #4 的引擎层验证（API 层验证由 Plan 07 E2E 完成）。
    """
    flow_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": flow_id}}

    initial_state: OffboardingState = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [],
        "context": {},
    }

    # 第一阶段：起流程 + 挂起
    graph_v1 = _build_state_graph().compile(checkpointer=saver)
    await graph_v1.ainvoke(initial_state, config=config)

    # 第二阶段："重启" — 用同一 saver 重建 graph，应能继续
    graph_v2 = _build_state_graph().compile(checkpointer=saver)
    resume_payload = {
        "action": "advance",
        "result_text": "重启后继续",
        "actor": "li.si",
    }
    final = await graph_v2.ainvoke(Command(resume=resume_payload), config=config)

    # 校验：apply 没被重跑（reducer 不会重复累计 apply）— 证明 checkpoint 恢复有效
    apply_count = sum(1 for r in final["node_results"] if r["node_name"] == "apply")
    assert (
        apply_count == 1
    ), f"apply node ran {apply_count} times (expected 1) — checkpoint not recovered"
    assert final["current_action"] == "advance"


# ---------------------------------------------------------------------------
# checkpointer CLI 入口校验
# ---------------------------------------------------------------------------
def test_checkpointer_module_has_cli_entry():
    """python -m offboarding_flow.flow_engine.checkpointer --setup 入口必须可调用。"""
    from offboarding_flow.flow_engine import checkpointer

    assert hasattr(checkpointer, "_run_setup_cli")
    assert hasattr(checkpointer, "setup_checkpointer_schema")
    assert hasattr(checkpointer, "make_checkpointer")
    assert hasattr(checkpointer, "dispose_checkpointer")
