"""applicant_summary_service — Slice 4C LLM-02。

为申请人最终确认节点 / 申请人确认邮件提供一段 AI 摘要。

设计:
- 不在节点函数里直接构造 LLMService — 节点函数接收 LLMService 实例（DI 友好）
- 失败 / 超时 → 返回 None；调用方（节点 / 邮件渲染）走"原始 timeline 无摘要"降级
- 输入用 list[dict] node_results（与 timeline_renderer 输入同形状）

调用关系:
applicant_final_confirm_node → applicant_summary(node_results, llm_service?) → str | None
邮件渲染 (Slice 4B 集成时) → applicant_summary(...) → wrap into 邮件正文头
"""

from __future__ import annotations

import json
import logging
from typing import Any

from offboarding_flow.llm.prompts import SUMMARIZE_FOR_APPLICANT_PROMPT
from offboarding_flow.services.llm_service import LLMService

logger = logging.getLogger(__name__)


async def applicant_summary(
    node_results: list[Any],
    llm_service: LLMService | None = None,
) -> str | None:
    """对申请人最终确认 timeline 生成一段中文一句话总结。

    Args:
        node_results: state.node_results 数组（list[NodeResult] / list[dict] 都兼容；
            用 list[Any] 避免循环 import flow_engine.state）
        llm_service: 可注入 LLMService（测试 mock 用）；None 时新建默认 GLM client

    Returns:
        包裹 disclaimer 的中文一句话总结；任何失败 → None（调用方走降级邮件）
    """
    if not node_results:
        logger.info("[applicant_summary] 空 node_results — 跳过摘要")
        return None

    service = llm_service if llm_service is not None else LLMService()
    # 只挑摘要必要字段，避免 token 浪费 — 任何 r 异常都吞掉返回 None
    try:
        compact = [
            {
                "node_title": r.get("node_title") or r.get("node_name", "?"),
                "result_text": (
                    r["result_text"].strip() if isinstance(r.get("result_text"), str) else ""
                ),
                "actor": r.get("actor", "unknown"),
                "action": r.get("action", "advance"),
            }
            for r in node_results
        ]
        node_results_json = json.dumps(compact, ensure_ascii=False)
    except (TypeError, ValueError, AttributeError) as e:
        logger.warning("[applicant_summary] node_results 序列化失败: %s", e)
        return None

    return await service.complete(
        SUMMARIZE_FOR_APPLICANT_PROMPT,
        {"node_results_json": node_results_json},
        # 摘要场景 — header + disclaimer 都加
        with_header=True,
        with_disclaimer=True,
    )


__all__ = ["applicant_summary"]
