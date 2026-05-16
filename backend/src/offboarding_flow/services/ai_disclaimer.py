"""AI 边界 disclaimer 工具 — LLM-06 / PRD §15.3。

约定:
- 所有 AI 生成的内容必须带 `🤖 AI 生成` 角标
- 报告 / 建议末尾固定 disclaimer
- Mattermost @bot 回复时显式标 `[AI 助手]`（由 bot 层 prepend，本模块不管）
"""

from __future__ import annotations

# PRD §15.3 固定文案 — 修改前请同步 PRD
AI_DISCLAIMER: str = "*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*"

AI_HEADER: str = "🤖 AI 生成"


def wrap_ai_output(text: str, *, with_header: bool = True) -> str:
    """给 AI 输出 prepend 角标 + append disclaimer。

    Args:
        text: 原始 AI 输出（已 strip 过的多行字符串）
        with_header: 是否加 🤖 角标（短建议加；markdown 报告不加避免破坏 # 标题层级）

    Returns:
        包裹后的字符串。空输入返回空（不带角标 / disclaimer，调用方负责降级到规则模板）。
    """
    if not text or not text.strip():
        return ""
    body = text.strip()
    parts: list[str] = []
    if with_header:
        parts.append(AI_HEADER)
        parts.append("")  # 空行隔开
    parts.append(body)
    parts.append("")  # 空行隔开
    parts.append("---")
    parts.append(AI_DISCLAIMER)
    return "\n".join(parts)
