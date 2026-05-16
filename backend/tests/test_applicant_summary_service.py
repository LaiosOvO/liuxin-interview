"""test_applicant_summary_service.py — Slice 4C LLM-02 单元测试。

applicant_summary 是申请人最终确认节点 + 邮件正文头部摘要的入口。

测试矩阵:
- 空 node_results → None（不调 LLM）
- 正常 node_results → LLMService 被调 + 含 disclaimer
- LLMService 返回 None → 函数返回 None（降级路径）
- 注入 mock service 验证 prompt 模板与 context
- 非序列化对象在 node_results 中 → None（不抛出）
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.llm.prompts import SUMMARIZE_FOR_APPLICANT_PROMPT
from offboarding_flow.services.applicant_summary_service import applicant_summary


def _sample_node_results() -> list[dict[str, Any]]:
    return [
        {
            "node_name": "apply",
            "node_title": "提交申请",
            "result_text": "申请已提交",
            "actor": "zhang.san",
            "completed_at": "2026-05-16T10:00:00+00:00",
        },
        {
            "node_name": "device_return",
            "node_title": "设备归还",
            "result_text": "笔记本 + 工牌已交回",
            "actor": "admin.frank",
            "completed_at": "2026-05-16T11:00:00+00:00",
        },
    ]


async def test_empty_node_results_returns_none() -> None:
    """空数组 → 不调 LLM，直接 None。"""
    service = MagicMock()
    service.complete = AsyncMock()
    result = await applicant_summary([], llm_service=service)
    assert result is None
    service.complete.assert_not_called()


async def test_normal_call_invokes_llm_with_summarize_template() -> None:
    """正常 node_results → LLMService.complete 被调 + 用 SUMMARIZE 模板 + 含 disclaimer。"""
    service = MagicMock()
    service.complete = AsyncMock(
        return_value="🤖 AI 生成\n\n你的离职流程已完成。\n\n---\n*由 AI 生成 ...*"
    )

    result = await applicant_summary(_sample_node_results(), llm_service=service)

    assert result is not None
    assert "你的离职流程已完成。" in result
    service.complete.assert_awaited_once()
    args, kwargs = service.complete.await_args
    # 第一个 arg 是模板
    assert args[0] is SUMMARIZE_FOR_APPLICANT_PROMPT
    # 第二个 arg 是 context dict
    ctx = args[1]
    assert "node_results_json" in ctx
    # 摘要的 JSON 字符串应该含两个节点 title
    assert "提交申请" in ctx["node_results_json"]
    assert "设备归还" in ctx["node_results_json"]


async def test_llm_returns_none_propagates() -> None:
    """LLMService 降级返回 None → applicant_summary 也返回 None（让调用方走规则模板）。"""
    service = MagicMock()
    service.complete = AsyncMock(return_value=None)
    result = await applicant_summary(_sample_node_results(), llm_service=service)
    assert result is None


async def test_with_header_and_disclaimer_flags_set_correctly() -> None:
    """摘要场景固定 with_header=True + with_disclaimer=True（LLM-06）。"""
    service = MagicMock()
    service.complete = AsyncMock(return_value="ok")
    await applicant_summary(_sample_node_results(), llm_service=service)
    kwargs = service.complete.await_args.kwargs
    assert kwargs.get("with_header") is True
    assert kwargs.get("with_disclaimer") is True


async def test_compact_node_results_strip_unused_fields() -> None:
    """传给 LLM 的 JSON 应该只含 title / result_text / actor / action，节省 token。"""
    service = MagicMock()
    service.complete = AsyncMock(return_value="ok")
    await applicant_summary(_sample_node_results(), llm_service=service)
    ctx = service.complete.await_args.args[1]
    json_str = ctx["node_results_json"]
    # 不含 completed_at（已剔除）
    assert "completed_at" not in json_str
    # 不含 node_name（用 node_title 替代）— 但保留 actor
    assert "zhang.san" in json_str


async def test_non_string_result_text_defensively_skipped() -> None:
    """node_results 含非 str result_text → 该字段被替换为 ""，不抛出（防御性）。

    LLM 仍被调用（mock 不抛），但 compact JSON 里 result_text 是空字符串。
    """
    import datetime

    service = MagicMock()
    service.complete = AsyncMock(return_value="ok")
    bad = [{"node_title": "x", "result_text": datetime.datetime.now()}]
    result = await applicant_summary(bad, llm_service=service)
    assert result == "ok"
    # JSON 里 result_text 已被替换为 ""
    ctx = service.complete.await_args.args[1]
    assert "datetime" not in ctx["node_results_json"]


async def test_non_dict_node_result_returns_none() -> None:
    """node_results 含完全异常元素（非 dict） → None（不抛出）。"""
    service = MagicMock()
    service.complete = AsyncMock()
    bad: list[Any] = ["not a dict"]  # type: ignore[list-item]
    result = await applicant_summary(bad, llm_service=service)
    assert result is None
    service.complete.assert_not_called()


async def test_default_service_lazily_constructed(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传 llm_service 时 — 函数应该 lazy 构造默认 LLMService（不立即连 GLM）。

    这里 monkeypatch LLMService.complete 让它直接返回 None，验证不会真连 GLM。
    """
    from offboarding_flow.services import llm_service as llm_mod

    async def fake_complete(self, *a: Any, **kw: Any) -> Any:
        return None

    monkeypatch.setattr(llm_mod.LLMService, "complete", fake_complete)
    result = await applicant_summary(_sample_node_results())
    assert result is None
