"""LLM 子包 — Slice 4C / Phase 4 LLM-01..06。

设计原则（user memory feedback `feedback_capability_design`）:
- LLM 能力用 **prompt 模板** 封装，不要每个能力单独写 class
- 一个 `LLMService` 调 GLM API + asyncio.timeout(8) + 失败降级
- 一个 `prompts.py` 含 3 个 prompt 模板（summarize / suggest / report）
- 所有 AI 输出自动 append 边界 disclaimer（PRD §15.3 LLM-06）
"""

from .glm_client import build_glm_client
from .prompts import (
    GENERATE_REPORT_PROMPT,
    SUGGEST_NEXT_STEP_PROMPT,
    SUMMARIZE_FOR_APPLICANT_PROMPT,
    render_prompt,
)

__all__ = [
    "build_glm_client",
    "GENERATE_REPORT_PROMPT",
    "SUGGEST_NEXT_STEP_PROMPT",
    "SUMMARIZE_FOR_APPLICANT_PROMPT",
    "render_prompt",
]
