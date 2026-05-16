"""Bot intent router — 白名单命令 parse 失败时调 LLM 分类 + 兜底通用 AI 问答。

链路：
  parse_command 失败 → 调 LLM (INTENT_ROUTER_PROMPT)
    → intent="start|status|list|meeting_ingest|users_sync|help" → 重新 dispatch
    → intent="ai_qa" → 直接回 ai_reply
    → confidence < 0.6 → 走 ai_qa

调用方：mattermost_listener / mattermost_webhook 在 BotCommandParseError 时调本模块。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from offboarding_flow.config import get_settings
from offboarding_flow.llm.prompts import INTENT_ROUTER_PROMPT
from offboarding_flow.services.bot_command_parser import (
    SELF_APPLY_SENTINEL,
    BotCommand,
    BotCommandParseError,
    parse_command,
)
from offboarding_flow.services.llm_service import LLMService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentResult:
    intent: str
    args: dict
    confidence: float
    ai_reply: str | None  # intent=ai_qa 时直接用
    raw: str  # LLM 原始返回（调试用）


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if m:
        return m.group(1).strip()
    return text


class BotIntentRouter:
    """LLM-based intent router — bot fallback。"""

    def __init__(self, llm: LLMService | None = None) -> None:
        self.llm = llm or LLMService()

    async def classify(
        self, *, message: str, sender_username: str, sender_role: str | None
    ) -> IntentResult:
        """对自然语言消息分类。失败默认 ai_qa + 通用降级回答。"""
        settings = get_settings()
        result = await self.llm.complete(
            INTENT_ROUTER_PROMPT,
            {
                "bot_username": settings.mattermost_bot_username,
                "message": message,
                "sender": sender_username,
                "sender_role": sender_role or "未注册",
            },
            with_disclaimer=False,
            with_header=False,
            timeout=20.0,
        )
        if not result:
            return IntentResult(
                intent="ai_qa",
                args={},
                confidence=0.0,
                ai_reply=(
                    "🤖 AI 暂时不可用，请稍后再试。"
                    "你可以 `@offboarding-bot help` 看支持的命令。\n\n"
                    "_由 AI 生成 — AI 不会自动操作任何节点_"
                ),
                raw="",
            )
        try:
            data = json.loads(_strip_json_fences(result))
        except json.JSONDecodeError:
            logger.warning("[intent_router] JSON 解析失败 raw=%r", result[:200])
            return IntentResult(
                intent="ai_qa",
                args={},
                confidence=0.0,
                ai_reply=result.strip()[:1000],  # 把原始 LLM 输出当回答
                raw=result,
            )
        return IntentResult(
            intent=str(data.get("intent", "ai_qa")).strip().lower(),
            args=data.get("args", {}) or {},
            confidence=float(data.get("confidence", 0.0)),
            ai_reply=(data.get("ai_reply") or "").strip() or None,
            raw=result,
        )

    def intent_to_bot_command(self, ir: IntentResult, sender_username: str) -> BotCommand | None:
        """把 IntentResult 转成 BotCommand（白名单格式）让 bot_service.dispatch 处理。

        ai_qa / 低置信度 → 返 None（调用方走 ai_reply 兜底）。
        """
        if ir.confidence < 0.6 or ir.intent == "ai_qa":
            return None
        intent = ir.intent
        a = ir.args
        try:
            if intent == "start":
                username = a.get("username") or sender_username
                if username == "self" or username == "我":
                    username = SELF_APPLY_SENTINEL
                return parse_command(f"start {username}")
            if intent == "status" and a.get("flow_id"):
                return parse_command(f"status {a['flow_id']}")
            if intent == "list":
                return parse_command("list")
            if intent == "report" and a.get("flow_id"):
                return parse_command(f"report {a['flow_id']}")
            if intent == "suggest" and a.get("flow_id"):
                return parse_command(f"suggest {a['flow_id']}")
            if intent == "users_sync":
                return parse_command("users-sync")
            if intent == "help":
                return parse_command("help")
            if intent == "meeting_ingest":
                raw = a.get("raw_text") or ""
                if raw and len(raw) >= 30:
                    return parse_command(f"meeting-ingest {raw}")
        except BotCommandParseError as e:
            logger.info("[intent_router] intent=%s parse 失败: %s", intent, e)
        return None
