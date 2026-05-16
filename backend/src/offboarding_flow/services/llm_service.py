"""LLMService — 统一 LLM 调用入口（Slice 4C / Phase 4 LLM-01..03）。

核心约束（PITFALLS #22 + PRD LLM-03）:
- asyncio.timeout(8) 硬性超时上限
- 任何异常 / 超时 / 空返回 → 返回 None，**绝不抛出**（调用方走规则模板兜底）
- 自动 append AI disclaimer（LLM-06）

设计取舍（用户 memory feedback `feedback_capability_design`）:
- 每个 LLM 能力 = 一组 prompt 模板（不是 class）
- LLMService.complete(template, context) 统一入口
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from offboarding_flow.config import get_settings
from offboarding_flow.llm.prompts import render_prompt
from offboarding_flow.services.ai_disclaimer import wrap_ai_output

logger = logging.getLogger(__name__)


class LLMService:
    """统一 LLM 调用入口 — 不感知具体业务（业务在 caller 决定用哪个 prompt）。"""

    def __init__(self, client: Any | None = None) -> None:
        """构造 LLMService。

        Args:
            client: 可选注入的 AsyncOpenAI client（测试 mock 用）；
                None 时 lazy 构造默认 GLM client。
        """
        self._client = client

    def _get_client(self) -> Any:
        """lazy 获取 client — 推迟到首次 complete 调用，方便测试不真连 GLM。"""
        if self._client is None:
            from offboarding_flow.llm.glm_client import build_glm_client

            self._client = build_glm_client()
        return self._client

    async def complete(
        self,
        template: tuple[str, str],
        context: dict[str, Any],
        *,
        timeout: float | None = None,
        with_disclaimer: bool = True,
        with_header: bool = True,
    ) -> str | None:
        """调 LLM 渲染 prompt 模板并返回结果。

        Args:
            template: prompts.py 中的 (system, user_template) 二元组
            context: 填充 user_template 占位符的 dict
            timeout: 单次超时秒数；None 时取 settings.glm_timeout_seconds（默认 8）
            with_disclaimer: 是否在结果末尾 append AI disclaimer（LLM-06）
            with_header: 是否在结果前加 🤖 角标

        Returns:
            包裹后的文本；任何异常 / 超时 / 空返回 → None（调用方走规则模板）。
        """
        settings = get_settings()
        actual_timeout = timeout if timeout is not None else settings.glm_timeout_seconds

        try:
            system, user = render_prompt(template, **context)
        except (KeyError, ValueError) as e:
            logger.warning("[llm] prompt 渲染失败 — context 缺占位符: %s", e)
            return None

        try:
            async with asyncio.timeout(actual_timeout):
                raw = await self._call_glm(system, user)
        except TimeoutError as e:
            logger.warning("[llm] 超时 %.1fs — 走规则模板降级: %s", actual_timeout, e)
            return None
        except Exception as e:
            logger.warning("[llm] 调用失败 — 走规则模板降级: %s", type(e).__name__)
            return None

        if not raw or not raw.strip():
            logger.warning("[llm] 返回空 — 走规则模板降级")
            return None

        if with_disclaimer:
            return wrap_ai_output(raw, with_header=with_header)
        return raw.strip()

    async def _call_glm(self, system: str, user: str) -> str:
        """实际 OpenAI 兼容 chat.completions 调用（无超时控制 — 由外层 asyncio.timeout 包）。"""
        settings = get_settings()
        client = self._get_client()
        # AsyncOpenAI 接口（STACK.md §4.6）
        response = await client.chat.completions.create(
            model=settings.glm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,  # 摘要类任务保守一点
        )
        # OpenAI 兼容响应结构
        if not response.choices:
            return ""
        content = response.choices[0].message.content
        return content or ""


__all__ = ["LLMService"]
