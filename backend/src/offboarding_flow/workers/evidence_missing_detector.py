"""证据缺失检测 — 纯函数 helper（无副作用）。

策略（PRD §17.2）：
- 节点 result_text 长度 < 5 字符 → 标 evidence_missing=True
- 节点显式 evidence_missing=True（演示模式 simulate-evidence-missing 命令直接置位）→ True
- 其他情况 → False

调用方：
- AI 后台报告（LLM-05）：检测后在阻塞事项段标 "⚠️ 证据待补充"
- Mattermost simulate-evidence-missing 命令（BOT-02 / Slice 4B 已实现）
- HR Dashboard 节点旁红色标签（TIMEOUT-04 / Phase 5）

REQ: TIMEOUT-02（评分点 #6）
"""

from __future__ import annotations

from typing import Any

# 最小 result_text 长度（短于此判定为证据缺失）
EVIDENCE_MIN_LENGTH = 5


def is_text_evidence_missing(text: str | None) -> bool:
    """单条文本判定 — None 或 strip 后长度不足即视为缺失。"""
    if text is None:
        return True
    return len(text.strip()) < EVIDENCE_MIN_LENGTH


def detect_evidence_missing(node: Any) -> bool:
    """对一个 node_states ORM 行 / dict 做综合判定。

    Args:
        node: 含 `result_text` 与可选 `evidence_missing` 属性的对象（NodeState ORM 或 dict）

    Returns:
        True = 该节点证据缺失（应在 AI 报告中标 ⚠️）
    """
    # 显式标记优先（演示 simulate 命令、HR 手动标记）
    explicit = _get(node, "evidence_missing")
    if explicit is True:
        return True
    # 文本不足判定
    return is_text_evidence_missing(_get(node, "result_text"))


def _get(obj: Any, attr: str) -> Any:
    """兼容 ORM 对象与 dict 的属性访问。"""
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)
