"""test_llm_service.py — Slice 4C LLMService 单元测试（LLM-01/02/03）。

测试矩阵:
- 正常 mock client 返回文本 → 包裹 disclaimer
- mock client raise TimeoutError → 返回 None（降级）
- mock client raise 其他 Exception → 返回 None（降级）
- mock client 返回空字符串 → 返回 None
- with_disclaimer=False → 不包裹
- with_header=False → 不加 🤖（markdown 报告）

不依赖真 GLM API — 全部 mock，无网络调用。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.llm.prompts import SUMMARIZE_FOR_APPLICANT_PROMPT
from offboarding_flow.services.ai_disclaimer import AI_DISCLAIMER, AI_HEADER
from offboarding_flow.services.llm_service import LLMService


def _build_mock_client(content: str | None = "测试摘要") -> Any:
    """构造一个伪 AsyncOpenAI client — chat.completions.create 返回固定 content。"""
    client = MagicMock()
    choice = MagicMock()
    choice.message = MagicMock(content=content)
    response = MagicMock(choices=[choice] if content is not None else [])
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


async def test_complete_normal_returns_wrapped_text() -> None:
    """正常返回 → header + body + disclaimer。"""
    client = _build_mock_client("张三的离职流程已完成。")
    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
    )
    assert out is not None
    assert "张三的离职流程已完成。" in out
    assert AI_HEADER in out
    assert AI_DISCLAIMER in out


async def test_complete_timeout_returns_none() -> None:
    """asyncio.TimeoutError → None（降级路径，PRD LLM-03）。"""
    client = MagicMock()

    async def hang(*_a: Any, **_kw: Any) -> Any:
        await asyncio.sleep(10)  # 远超 timeout

    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = hang

    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
        timeout=0.1,  # 强制超时
    )
    assert out is None


async def test_complete_exception_returns_none() -> None:
    """任意异常 → None（绝不抛出，PITFALLS #22）。"""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
    )
    assert out is None


async def test_complete_empty_content_returns_none() -> None:
    """LLM 返回空 → None（让调用方走规则模板）。"""
    client = _build_mock_client("")
    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
    )
    assert out is None


async def test_complete_whitespace_only_returns_none() -> None:
    """LLM 返回全空白 → None。"""
    client = _build_mock_client("   \n\n")
    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
    )
    assert out is None


async def test_complete_without_disclaimer() -> None:
    """with_disclaimer=False → 仅返回原文。"""
    client = _build_mock_client("纯文本")
    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
        with_disclaimer=False,
    )
    assert out == "纯文本"
    assert AI_HEADER not in (out or "")
    assert AI_DISCLAIMER not in (out or "")


async def test_complete_without_header_for_markdown_report() -> None:
    """LLM-05 报告场景 — markdown 不加 🤖 角标避免破坏标题层级。"""
    client = _build_mock_client("# 报告标题\n\n## 1. 进度")
    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
        with_header=False,
    )
    assert out is not None
    assert AI_HEADER not in out
    assert "# 报告标题" in out
    assert AI_DISCLAIMER in out  # disclaimer 仍然要有


async def test_complete_missing_context_placeholder_returns_none() -> None:
    """prompt 模板缺占位符 → None（不抛出）。"""
    client = _build_mock_client("不会被调用")
    service = LLMService(client=client)
    out = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {},  # 缺 node_results_json
    )
    assert out is None


async def test_complete_passes_temperature_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 chat.completions.create 调用参数正确（model / messages）。"""
    client = _build_mock_client("ok")
    service = LLMService(client=client)
    await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": "[]"},
    )
    # 检查 create 被调用 + 传了 messages
    create_call = client.chat.completions.create
    assert create_call.await_count == 1
    kwargs = create_call.await_args.kwargs
    assert "model" in kwargs
    assert "messages" in kwargs
    msgs = kwargs["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
