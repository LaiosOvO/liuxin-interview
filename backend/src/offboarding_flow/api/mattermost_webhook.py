"""POST /api/mattermost/webhook — Mattermost Outgoing Webhook 入站端点（BOT-01）。

Mattermost Outgoing Webhook 在 trigger word（`@offboarding-bot`）被命中时
向本端点 POST form-data（与 Slack 兼容格式）：
  - token: webhook 配置的 token（必须与 settings.mattermost_outgoing_webhook_token 一致）
  - team_id / team_domain
  - channel_id / channel_name
  - timestamp
  - user_id / user_name
  - text: 完整原始文本（如 "@offboarding-bot start zhang.san"）
  - trigger_word: 命中的 trigger（如 "@offboarding-bot"）

返回 200 + JSON {"text": "..."} 让 Mattermost 在频道里渲染（备用渠道）；
同时主动用 PAT 走 /api/v4/posts 发回复（PRD §16.3 出站通道）。

安全约束（PRD §16.5）：
- Token 校验防伪造（不一致返回 401）
- 命令解析用 bot_command_parser（白名单 + 严格正则）
- start 命令在 bot_service 内部做 role 校验
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.api.deps import SessionDep, get_flow_service
from offboarding_flow.config import Settings, get_settings
from offboarding_flow.services.bot_command_parser import (
    BotCommandParseError,
    parse_command,
)
from offboarding_flow.services.bot_service import (
    BotFlowNotFoundError,
    BotInvocationContext,
    BotPermissionError,
    BotService,
)
from offboarding_flow.services.flow_service import FlowService
from offboarding_flow.state_store.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mattermost", tags=["mattermost"])


async def _resolve_user_role(session: AsyncSession, user_name: str) -> str | None:
    """从业务 users 表查 Mattermost user_name → role 映射。

    未注册返回 None（bot_service 内部 BOT-04 校验会拒绝 start）。
    """
    stmt = select(User).where(User.username == user_name)
    user = (await session.execute(stmt)).scalar_one_or_none()
    return user.role if user else None


@router.post("/webhook")
async def mattermost_outgoing_webhook(
    session: SessionDep,
    flow_service: Annotated[FlowService, Depends(get_flow_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    # Mattermost Outgoing Webhook 用 application/x-www-form-urlencoded
    token: Annotated[str, Form()],
    text: Annotated[str, Form()],
    user_id: Annotated[str, Form()] = "",
    user_name: Annotated[str, Form()] = "",
    channel_id: Annotated[str, Form()] = "",
    channel_name: Annotated[str, Form()] = "",
    trigger_word: Annotated[str, Form()] = "",
    team_id: Annotated[str, Form()] = "",
    team_domain: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """处理 Mattermost Outgoing Webhook。

    返回 Mattermost-compatible JSON：{"text": "<reply>", "response_type": "in_channel"}
    """
    # 1. Token 校验防伪造（PRD §16.5）
    expected = settings.mattermost_outgoing_webhook_token
    if not expected or token != expected:
        logger.warning(
            "[mattermost_webhook] token 不匹配 user=%s trigger=%s",
            user_name,
            trigger_word,
        )
        raise HTTPException(status_code=401, detail="无效 webhook token")

    # 2. 解析命令
    try:
        cmd = parse_command(text)
    except BotCommandParseError as e:
        logger.info("[mattermost_webhook] 解析失败: %s text=%r", e, text)
        return {
            "text": f"⚠️ {e}\n输入 `@offboarding-bot help` 查看可用命令",
            "response_type": "in_channel",
        }

    # 3. 查调用者业务 role（BOT-04 start 命令要用）
    user_role = await _resolve_user_role(session, user_name)
    ctx = BotInvocationContext(
        user_name=user_name,
        user_id=user_id,
        channel_id=channel_id,
        user_role=user_role,
    )

    # 4. 分发
    bot_service = BotService(session=session, flow_service=flow_service)
    try:
        reply = await bot_service.dispatch(cmd, ctx)
    except BotPermissionError as e:
        logger.info("[mattermost_webhook] 权限拒绝: %s", e)
        return {"text": f"🚫 {e}", "response_type": "in_channel"}
    except BotFlowNotFoundError as e:
        logger.info("[mattermost_webhook] flow 不存在: %s", e)
        return {"text": f"⚠️ {e}", "response_type": "in_channel"}
    except Exception as e:
        # 不让内部异常细节泄漏到 channel
        logger.exception(
            "[mattermost_webhook] 命令处理异常 cmd=%s args=%s: %s",
            cmd.name,
            cmd.args,
            e,
        )
        return {
            "text": f"⚠️ 命令 `{cmd.name}` 处理失败；HR 请查看服务器日志",
            "response_type": "in_channel",
        }

    return {"text": reply, "response_type": "in_channel"}
