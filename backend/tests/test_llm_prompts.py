"""test_llm_prompts.py — Slice 4C 3 个 prompt 模板渲染测试（LLM-02/04/05）。

测试矩阵:
- 3 个模板都是 (system, user_template) 二元组
- render_prompt 正确填充占位符
- 缺占位符 → KeyError（调用方 LLMService 捕获返回 None）
- system 段含 PRD 关键要求（≤ 100 字 / ≤ 200 字 / 四要素 / 4 段）
"""

from __future__ import annotations

import json

import pytest

from offboarding_flow.llm.prompts import (
    GENERATE_REPORT_PROMPT,
    SUGGEST_NEXT_STEP_PROMPT,
    SUMMARIZE_FOR_APPLICANT_PROMPT,
    render_prompt,
)


def test_all_templates_are_tuples_of_two_strings() -> None:
    """3 个模板形状统一 — (system, user_template)。"""
    for t in (
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        SUGGEST_NEXT_STEP_PROMPT,
        GENERATE_REPORT_PROMPT,
    ):
        assert isinstance(t, tuple)
        assert len(t) == 2
        assert all(isinstance(x, str) for x in t)


def test_summarize_template_renders() -> None:
    """LLM-02 — 填充 node_results_json 后 user 段含 JSON。"""
    data = [{"node_name": "apply", "result_text": "申请提交"}]
    system, user = render_prompt(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        node_results_json=json.dumps(data, ensure_ascii=False),
    )
    assert "申请提交" in user
    assert "≤ 100 字" in system  # PRD §4.5.2 摘要长度约束


def test_summarize_template_system_constraints() -> None:
    """system 段必须含 PRD §4.5.2 关键约束。"""
    system, _ = SUMMARIZE_FOR_APPLICANT_PROMPT
    assert "一句话" in system
    assert "100 字" in system
    assert "第三人称" in system


def test_suggest_template_renders() -> None:
    """LLM-04 — 填充 flow_summary_json / nodes_text / actions_text。"""
    system, user = render_prompt(
        SUGGEST_NEXT_STEP_PROMPT,
        flow_summary_json='{"flow_id": "abc", "status": "active"}',
        nodes_text="- knowledge_handover (in_progress, li.si)",
        actions_text="- li.si advance hr_initial @ 10:00",
    )
    assert "abc" in user
    assert "knowledge_handover" in user
    assert "li.si advance" in user


def test_suggest_template_four_elements() -> None:
    """PRD §15.1 — 四要素必须出现在 system prompt 里。"""
    system, _ = SUGGEST_NEXT_STEP_PROMPT
    assert "当前节点" in system
    assert "阻塞原因" in system
    assert "推荐操作" in system
    assert "责任人" in system
    assert "200 字" in system
    # AI 不允许自动操作
    assert "AI 自动操作" in system or "不要建议执行动作" in system


def test_report_template_renders() -> None:
    """LLM-05 — 报告模板渲染。"""
    system, user = render_prompt(
        GENERATE_REPORT_PROMPT,
        flow_summary_json='{"flow_id": "xyz"}',
        nodes_text="- apply (completed)",
        actions_text="- hr.alice advance @ 09:00",
    )
    assert "xyz" in user
    assert "apply (completed)" in user


def test_report_template_four_sections() -> None:
    """PRD §15.2 — 4 段必须出现在 system prompt。"""
    system, _ = GENERATE_REPORT_PROMPT
    assert "当前进度" in system
    assert "阻塞事项" in system
    assert "是否需要真人协助" in system
    assert "建议下一步" in system
    assert "markdown" in system.lower()


def test_render_prompt_missing_placeholder_raises_keyerror() -> None:
    """缺占位符 → KeyError（LLMService 捕获后降级）。"""
    with pytest.raises(KeyError):
        render_prompt(SUMMARIZE_FOR_APPLICANT_PROMPT)  # 缺 node_results_json


def test_render_prompt_extra_kwargs_silently_ignored() -> None:
    """多余 kwargs format 不抛错 — pep-3101 行为。"""
    _, user = render_prompt(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        node_results_json="[]",
        unknown_extra="忽略",
    )
    assert "[]" in user
