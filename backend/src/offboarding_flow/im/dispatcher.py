"""dispatch_message — IM 平台无关的"消息 → 业务命令"分发函数（ABS-02）。

来源：从 `workers/mattermost_listener.py:_handle_event` 行 175-262 抽取。
本函数对所有 IM listener（MM / Huly / Lark）公用，listener 仅负责：
1. 解析平台原生事件（WS / Webhook / HTTP poll）
2. 过滤 bot 自己发的消息 + 触发条件（DM / @mention / 关键词）
3. 抽出 sender_username / channel_id / channel_type / message
4. 构造 IMHelpers（封装平台特定回写 API）
5. 调用 `dispatch_message(...)`

本函数负责：
1. parse_command（白名单）
2. 失败 → LLM intent router 兜底
3. 查 sender_role（业务 DB users 表）
4. 构造 BotInvocationContext（含 IM 回写回调，用 dict 兼容 Phase 7 接口）
5. BotService.dispatch
6. 统一异常 → 友好 markdown 回复
7. 通过 im_helpers.post_channel 回写

设计约束（CLAUDE.md §3.4 节点幂等）：
- listener 端可能因 WS 重连而重复推同一条 message；本函数不做幂等去重，
  依赖业务命令 handler 自己的幂等（如 start 命令的 flow_id upsert）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy import select

from offboarding_flow.im.context import IMHelpers
from offboarding_flow.services.bot_command_parser import (
    BotCommand,  # 类型注解占位（在 _resolve_via_intent_router 注解）
    BotCommandParseError,
    parse_command,
)
from offboarding_flow.services.bot_service import (
    BotFlowNotFoundError,
    BotInvocationContext,
    BotPermissionError,
    BotService,
)
from offboarding_flow.state_store.models import User

logger = logging.getLogger(__name__)


# Type alias for session factory（async context manager 返回 AsyncSession）
SessionFactory = Callable[[], AbstractAsyncContextManager[Any]]


async def _resolve_user_role(session: Any, username: str) -> str | None:
    """从 users 表查 sender 的业务 role（与 MattermostListener._resolve_user_role 同语义）。"""
    stmt = select(User).where(User.username == username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    return user.role if user else None


async def _resolve_via_intent_router(
    *,
    message: str,
    sender_username: str,
    sender_role: str | None,
    im_helpers: IMHelpers,
    channel_id: str,
    parse_err: BotCommandParseError,
) -> BotCommand | None:
    """白名单 parse 失败 → 调 LLM intent router 兜底。

    Returns:
        BotCommand: 路由出合法命令则返回，由调用方继续 dispatch
        None: ai_qa / router 失败 — 此时已用 im_helpers.post_channel 写过回复，
            调用方应直接 return（不要继续往下 dispatch）。
    """
    # 懒 import 避免启动期循环依赖 + 避免单测 mock 时拉 LLM 实例
    from offboarding_flow.services.bot_intent_router import BotIntentRouter

    try:
        router = BotIntentRouter()
        ir = await router.classify(
            message=message,
            sender_username=sender_username,
            sender_role=sender_role,
        )
        logger.info(
            "[dispatcher] intent=%s conf=%.2f args=%s",
            ir.intent,
            ir.confidence,
            list(ir.args.keys()),
        )
        fallback_cmd = router.intent_to_bot_command(ir, sender_username)
        if fallback_cmd is None:
            # ai_qa 路径 — 直接发 LLM 回答（与 MattermostListener 行 199-207 同语义）
            ai_text = ir.ai_reply or (
                "🤖 我没听懂你的意思。可以试试：\n"
                "- `@offboarding-bot help` 看命令清单\n"
                "- 直接发 `我要离职` 自助起流程\n"
                "- 粘贴会议纪要让我整理"
            )
            await im_helpers.post_channel(channel_id, ai_text)
            return None
        return fallback_cmd
    except Exception as router_exc:
        logger.warning("[dispatcher] intent router 失败: %s", router_exc)
        await im_helpers.post_channel(
            channel_id,
            f"⚠️ {parse_err}\n输入 `@offboarding-bot help` 查看可用命令",
        )
        return None


def _helpers_to_dict(im_helpers: IMHelpers) -> dict[str, Any]:
    """把 IMHelpers dataclass 转 dict 喂给 Phase 7 的 BotInvocationContext.mm_helpers。

    Plan 02 ABS-05 重构 BotInvocationContext 时此适配函数可删；
    本 plan 保持 BotService 端 0 改动，避免冲击现有 11 个命令 handler。
    """
    data: dict[str, Any] = {
        "post_channel": im_helpers.post_channel,
        "send_dm": im_helpers.send_dm,
    }
    if im_helpers.ensure_in_channel is not None:
        data["ensure_in_channel"] = im_helpers.ensure_in_channel
    return data


async def dispatch_message(
    *,
    sender_username: str,
    user_id: str,
    channel_id: str,
    channel_type: str,  # 'D' = DM, 'O' = public, 'P' = private（沿用 MM 约定）
    message: str,
    im_helpers: IMHelpers,
    settings: Any,
    session_factory: SessionFactory,
) -> None:
    """IM 平台无关的消息分发主入口（ABS-02）。

    Args:
        sender_username: 业务侧 username（如 "hr.alice"）；listener 须已去 @mention 前缀
        user_id: IM 平台原生 user id（备用；当前 BotService 不用）
        channel_id: IM 平台 channel id（回写时用）
        channel_type: 'D' / 'O' / 'P'（MM 约定，其他 IM 实现需映射）
        message: 用户消息原文（listener 已去 bot @mention 前缀更佳，但 parser 也能容错）
        im_helpers: 平台特定回写回调集合
        settings: 全局 Settings（供 BotService 内部需要 outline / mm token 用）
        session_factory: 返回 async context manager 的 callable，每个调用产新 session

    Raises: 不抛 — 所有异常都转成 user-friendly markdown 回写到 channel。
    """
    # ───────── 1. 解析命令（白名单优先，失败 LLM 兜底）─────────
    cmd: BotCommand | None
    try:
        cmd = parse_command(message)
    except BotCommandParseError as parse_err:
        # 兜底前需先解析 sender_role（intent_router prompt 用）
        async with session_factory() as s2:
            sender_role = await _resolve_user_role(s2, sender_username)
        cmd = await _resolve_via_intent_router(
            message=message,
            sender_username=sender_username,
            sender_role=sender_role,
            im_helpers=im_helpers,
            channel_id=channel_id,
            parse_err=parse_err,
        )
        if cmd is None:
            # ai_qa 路径已写回，结束
            return

    # ───────── 2. 业务编排（与 MattermostListener 行 217-262 同语义）─────────
    # 懒 import 避免启动期循环依赖
    from offboarding_flow.flow_engine.graph import get_graph
    from offboarding_flow.notifications.outbox_repository import OutboxRepository
    from offboarding_flow.services import FlowService, NotificationService
    from offboarding_flow.state_store.repositories import (
        ActionRepository,
        FlowRepository,
        NodeRepository,
    )

    async with session_factory() as session:
        user_role = await _resolve_user_role(session, sender_username)
        ctx = BotInvocationContext(
            user_name=sender_username,
            user_id=user_id,
            channel_id=channel_id,
            user_role=user_role,
            mm_helpers=_helpers_to_dict(im_helpers),
        )
        flow_repo = FlowRepository(session)
        node_repo = NodeRepository(session)
        action_repo = ActionRepository(session)
        outbox_repo = OutboxRepository(session)
        notif = NotificationService(session=session, outbox_repo=outbox_repo, settings=settings)
        flow_service = FlowService(
            session,
            flow_repo,
            node_repo,
            action_repo,
            get_graph(),
            notification_service=notif,
        )
        bot_service = BotService(session=session, flow_service=flow_service)
        try:
            reply = await bot_service.dispatch(cmd, ctx)
        except BotPermissionError as e:
            reply = f"🚫 {e}"
        except BotFlowNotFoundError as e:
            reply = f"⚠️ {e}"
        except Exception as e:
            logger.exception("[dispatcher] dispatch error: %s", e)
            reply = "⚠️ 命令处理失败，请联系管理员"

    # ───────── 3. 回写 ─────────
    await im_helpers.post_channel(channel_id, reply)


__all__ = ["dispatch_message", "SessionFactory"]
