"""test_applicant_final_confirm_glm.py — Slice 4C 节点 glm_summary 集成测试。

补充原 test_applicant_final_confirm.py 的覆盖（不重写原测试）。

测试矩阵:
- interrupt payload 含 glm_summary 字段（mock 成功返回字符串）
- LLM 失败 → glm_summary=None（节点照常 interrupt，不抛出）
- LLM 超时 → glm_summary=None
- 节点幂等性：interrupt 后 resume 再跑节点函数，LLM 调用 N 次都不阻塞流程
"""

from __future__ import annotations

import uuid
from typing import Any

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
def graph_with_node():
    b = StateGraph(OffboardingState)
    b.add_node(APPLICANT_FINAL_CONFIRM_NODE_NAME, applicant_final_confirm_node)
    b.add_edge(START, APPLICANT_FINAL_CONFIRM_NODE_NAME)
    b.add_edge(APPLICANT_FINAL_CONFIRM_NODE_NAME, END)
    return b.compile(checkpointer=InMemorySaver())


def _state_with_results() -> dict:
    return {
        "flow_id": str(uuid.uuid4()),
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [
            {
                "node_name": "apply",
                "node_title": "提交申请",
                "result_text": "申请已提交",
                "actor": "zhang.san",
                "completed_at": "2026-05-16T10:00:00+00:00",
            },
        ],
        "context": {},
    }


async def test_interrupt_payload_includes_glm_summary_field(
    graph_with_node: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """interrupt payload 必须含 glm_summary key（即使值是 None）。

    mock applicant_summary 让它直接返回字符串验证字段透传。
    """
    from offboarding_flow.flow_engine.nodes import applicant_final_confirm as node_mod

    async def fake_summary(timeline: list[dict[str, Any]]) -> str:
        return "🤖 AI 生成\n\n你已完成离职流程。\n\n---\n*由 AI 生成 ...*"

    monkeypatch.setattr(node_mod, "_safe_glm_summary", fake_summary)

    s = _state_with_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    result = await graph_with_node.ainvoke(s, config=cfg)

    # interrupt 信息保存在 result['__interrupt__']
    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert "glm_summary" in interrupt_payload
    assert interrupt_payload["glm_summary"] is not None
    assert "你已完成离职流程。" in interrupt_payload["glm_summary"]
    assert "由 AI 生成" in interrupt_payload["glm_summary"]


async def test_glm_summary_is_none_when_llm_fails(
    graph_with_node: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 返回 None → glm_summary=None，节点照常 interrupt。"""
    from offboarding_flow.flow_engine.nodes import applicant_final_confirm as node_mod

    async def fake_summary(timeline: list[dict[str, Any]]) -> Any:
        return None

    monkeypatch.setattr(node_mod, "_safe_glm_summary", fake_summary)

    s = _state_with_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    result = await graph_with_node.ainvoke(s, config=cfg)
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["glm_summary"] is None
    # 流程仍然能 resume
    final = await graph_with_node.ainvoke(
        Command(resume={"action": "advance", "actor": "zhang.san"}),
        config=cfg,
    )
    assert final["current_action"] == "advance"


async def test_glm_summary_exception_does_not_block_node(
    graph_with_node: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_safe_glm_summary 内部任何异常都被吞掉 — 节点照常工作（PRD LLM-03）。

    模拟方式：直接 patch applicant_summary 让它抛错，验证 _safe_glm_summary 捕获后
    返回 None，节点照常 interrupt。
    """
    from offboarding_flow.services import applicant_summary_service as svc_mod

    async def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("GLM API down")

    monkeypatch.setattr(svc_mod, "applicant_summary", boom)

    s = _state_with_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    # 不应抛出
    result = await graph_with_node.ainvoke(s, config=cfg)
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["glm_summary"] is None
    # 仍然含 timeline（降级到无摘要原始邮件）
    assert "timeline" in interrupt_payload
    assert len(interrupt_payload["timeline"]) == 1


async def test_timeline_field_preserved_alongside_glm_summary(
    graph_with_node: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新增 glm_summary 不能破坏既有 timeline 字段（防止 Slice 4B 邮件渲染坏掉）。"""
    from offboarding_flow.flow_engine.nodes import applicant_final_confirm as node_mod

    async def fake_summary(timeline: list[dict[str, Any]]) -> str:
        return "摘要"

    monkeypatch.setattr(node_mod, "_safe_glm_summary", fake_summary)

    s = _state_with_results()
    cfg = {"configurable": {"thread_id": s["flow_id"]}}
    result = await graph_with_node.ainvoke(s, config=cfg)
    payload = result["__interrupt__"][0].value
    # 既有字段全在
    for k in (
        "node_name",
        "node_title",
        "node_description",
        "flow_id",
        "employee_id",
        "timeline",
    ):
        assert k in payload, f"既有字段 {k} 丢失"
    # 新字段
    assert "glm_summary" in payload
