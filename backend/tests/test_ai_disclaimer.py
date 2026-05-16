"""test_ai_disclaimer.py — Slice 4C LLM-06 / PRD §15.3。

测试矩阵:
- 正常文本 → header + body + disclaimer
- 空 / 空白 → 空字符串（调用方走规则模板）
- with_header=False → 仅 body + disclaimer（markdown 报告场景）
- AI_DISCLAIMER 文案锁定（PRD §15.3 固定要求）
"""

from __future__ import annotations

from offboarding_flow.services.ai_disclaimer import (
    AI_DISCLAIMER,
    AI_HEADER,
    wrap_ai_output,
)


def test_wrap_ai_output_normal() -> None:
    """正常文本 → header + 空行 + body + 空行 + --- + disclaimer。"""
    out = wrap_ai_output("张三的设备已归还、权限已回收。")
    assert AI_HEADER in out
    assert "张三的设备已归还、权限已回收。" in out
    assert AI_DISCLAIMER in out
    assert "---" in out
    # 头尾顺序
    assert out.index(AI_HEADER) < out.index("张三")
    assert out.index("张三") < out.index(AI_DISCLAIMER)


def test_wrap_ai_output_empty_returns_empty() -> None:
    """空输入 → 空字符串（让调用方走规则模板）。"""
    assert wrap_ai_output("") == ""
    assert wrap_ai_output("   ") == ""
    assert wrap_ai_output("\n\n") == ""


def test_wrap_ai_output_without_header() -> None:
    """markdown 报告场景 — 不加 🤖 角标避免破坏 # 标题层级。"""
    out = wrap_ai_output("# 流程报告\n\n## 1. 当前进度", with_header=False)
    assert AI_HEADER not in out
    assert "# 流程报告" in out
    assert AI_DISCLAIMER in out


def test_disclaimer_content_locked() -> None:
    """PRD §15.3 锁定文案 — 防止改坏。"""
    assert "由 AI 生成" in AI_DISCLAIMER
    assert "HR 人工确认" in AI_DISCLAIMER
    assert "AI 不会自动操作任何节点" in AI_DISCLAIMER


def test_header_emoji_is_robot() -> None:
    """🤖 是评分点 #8 要求的 UI 标识。"""
    assert "🤖" in AI_HEADER
    assert "AI 生成" in AI_HEADER


def test_wrap_ai_output_strips_input() -> None:
    """前后空白被 strip — 输出格式干净。"""
    out = wrap_ai_output("  \n张三\n  ")
    # body 部分应该被 strip
    lines = out.split("\n")
    # 找到 body 行
    assert "张三" in lines
