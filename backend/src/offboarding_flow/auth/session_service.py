"""exchange_token 7 步校验链 — PRD §6.2.2 锁定。

约定（CONTEXT §D8 + §D12）：
- 校验顺序：JWT decode → SET NX EX 消费 jti → node 校验 → user 校验 → 注册 node SET → 签 session → 返回 redirect
- 任一失败抛 AuthError（reason 字段区分细节供 log）
- 全部失败对外统一 detail='鉴权失败' 不暴露具体原因
- jti 消费必须在 node 校验之前（防双击 race，PITFALLS #6）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.config import get_settings
from offboarding_flow.state_store.enums import NodeStatus
from offboarding_flow.state_store.repositories import NodeRepository, UserRepository

from . import jti_service, jwt_service, role_router
from .errors import AuthError, TokenAlreadyConsumedError
from .schemas import JWTPayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExchangeResult:
    """exchange_token 成功返回值。"""

    session_token: str  # 给前端的 cookie JWT
    redirect_to: str  # 角色对应前端路径
    role: str  # 透传 payload.role 便于前端显示
    name: str  # user.display_name 或 fallback username


async def exchange_token(
    token: str,
    redis: Redis,
    session: AsyncSession,
) -> ExchangeResult:
    """7 步校验链 — 任一失败抛 AuthError。

    Steps:
        1. JWT decode + 验签 + exp 校验
        2. SET NX EX 原子消费 jti（防双击 race）
        3. node 存在 + 同 flow_id + status=waiting_human + assignee == sub
        4. user 存在 + role 一致
        5. 注册 node:jti:{id} SET（后续可批量失效）
        6. 签 session cookie payload
        7. 返回 redirect_to（按 role 路由）
    """
    settings = get_settings()

    # 1. JWT decode（jwt_service 内部转 AuthError 子类）
    payload: JWTPayload = jwt_service.decode(token)
    jti_prefix = payload.jti[:8]
    logger.info(
        "[auth.exchange] start jti=%s... sub=%s flow=%s node=%s",
        jti_prefix,
        payload.sub,
        payload.flow_id,
        payload.node_id,
    )

    # 2. SET NX EX 原子消费 jti — 必须放在 node 校验之前（防双击 race，PITFALLS #6）
    consumed = await jti_service.consume_jti(
        redis,
        payload.jti,
        ttl_seconds=settings.token_expiry_hours * 3600,
    )
    if not consumed:
        logger.warning("[auth.exchange] reject reason=jti_replay jti=%s...", jti_prefix)
        raise TokenAlreadyConsumedError()

    # 3. node 校验
    node_repo = NodeRepository(session)
    node = await node_repo.get(payload.node_id)
    if node is None:
        logger.warning("[auth.exchange] reject reason=node_not_found jti=%s...", jti_prefix)
        raise AuthError(reason="node_not_found")
    if str(node.flow_id) != str(payload.flow_id):
        logger.warning(
            "[auth.exchange] reject reason=cross_flow jti=%s... payload.flow=%s node.flow=%s",
            jti_prefix,
            payload.flow_id,
            node.flow_id,
        )
        raise AuthError(reason="cross_flow")
    if node.status != NodeStatus.WAITING_HUMAN.value:
        logger.warning(
            "[auth.exchange] reject reason=node_not_waiting jti=%s... status=%s",
            jti_prefix,
            node.status,
        )
        raise AuthError(reason="node_not_waiting")
    if node.assignee != payload.sub:
        logger.warning(
            "[auth.exchange] reject reason=sub_mismatch jti=%s... payload.sub=%s assignee=%s",
            jti_prefix,
            payload.sub,
            node.assignee,
        )
        raise AuthError(reason="sub_mismatch")

    # 4. user 校验
    user_repo = UserRepository(session)
    user = await user_repo.get_by_username(payload.sub)
    if user is None:
        logger.warning("[auth.exchange] reject reason=user_not_found jti=%s...", jti_prefix)
        raise AuthError(reason="user_not_found")
    # user.role 是 String column，存的就是 enum.value
    user_role = user.role
    if user_role != payload.role:
        logger.warning(
            "[auth.exchange] reject reason=role_mismatch jti=%s... payload.role=%s user.role=%s",
            jti_prefix,
            payload.role,
            user_role,
        )
        raise AuthError(reason="role_mismatch")

    # 5. 注册 node:jti:{id} SET
    await jti_service.register_node_token(
        redis,
        payload.node_id,
        payload.jti,
        ttl_seconds=settings.token_expiry_hours * 3600,
    )

    # 6. 签 session cookie
    session_token = jwt_service.encode_session(payload)

    # 7. 返回 redirect_to
    redirect_to = role_router.resolve_redirect(
        payload.role,
        payload.flow_id,
        payload.node_id,
    )
    display_name = user.display_name if user.display_name else user.username

    logger.info(
        "[auth.exchange] success jti=%s... sub=%s redirect=%s",
        jti_prefix,
        payload.sub,
        redirect_to,
    )
    return ExchangeResult(
        session_token=session_token,
        redirect_to=redirect_to,
        role=payload.role,
        name=display_name,
    )
