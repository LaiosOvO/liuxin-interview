"""test_llm_real_glm.py — Slice 4C 真 GLM API 集成测试（默认 SKIP）。

启用方式:
    GLM_API_KEY=<真 key> uv run pytest tests/integration/test_llm_real_glm.py -m integration

设计:
- 默认 skip（CI 不依赖外部 API key）
- 仅当 GLM_API_KEY 既存在又非占位符时才跑
- 验证 prompt 模板能真跑通 + 返回非空中文输出
"""

from __future__ import annotations

import json
import os

import pytest

from offboarding_flow.llm.prompts import SUMMARIZE_FOR_APPLICANT_PROMPT
from offboarding_flow.services.llm_service import LLMService

_PLACEHOLDER_KEYS = {"", "changeme_in_real_env", "__zhipu_api_key__"}


def _real_glm_key_available() -> bool:
    return os.environ.get("GLM_API_KEY", "") not in _PLACEHOLDER_KEYS


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _real_glm_key_available(),
        reason="未设置真 GLM_API_KEY — 跳过真 API 集成测试",
    ),
]


async def test_summarize_real_glm_returns_non_empty_chinese() -> None:
    """真 GLM 跑 SUMMARIZE 模板 — 应该返回包含中文 + disclaimer 的非空字符串。"""
    service = LLMService()
    data = [
        {"node_title": "提交申请", "result_text": "申请已提交", "actor": "zhang.san"},
    ]
    result = await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": json.dumps(data, ensure_ascii=False)},
        timeout=10.0,
    )
    assert result is not None
    assert len(result) > 0
    # 含中文字符
    assert any("一" <= ch <= "鿿" for ch in result)
    # 含 disclaimer
    assert "由 AI 生成" in result
