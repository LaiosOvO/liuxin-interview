"""HulyPlatformClient — 一站式 facade，封装 connect + RestClient + TxOperations。

业务 caller 只需:
    pc = await connect_huly(
        accounts_url='http://192.168.2.44:8087/_accounts',
        admin_email='admin@x',
        admin_password='...',
        workspace_url='laios',
    )
    # 然后 pc.ops / pc.rest / pc.account 都可用
    doc_id = await pc.ops.create_doc(...)
    docs = await pc.rest.find_all(...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .rest_client import AccountInfo, HulyRestClient
from .tx_operations import TxOperations

logger = logging.getLogger(__name__)


@dataclass
class HulyPlatformClient:
    """已 connect 的 Huly 客户端 — 持 REST client + Account + TxOperations。"""

    rest: HulyRestClient
    account: AccountInfo
    ops: TxOperations

    @property
    def bot_account(self) -> str:
        """业务上 bot 的 PersonId / SocialId（用于审计 modifiedBy / Tx 提交者）。"""
        return self.account.primary_social_id


async def connect_huly(
    *,
    accounts_url: str,
    admin_email: str,
    admin_password: str,
    workspace_url: str,
    timeout: float = 15.0,
) -> HulyPlatformClient:
    """完整 connect 流程 — login + selectWorkspace + getAccount + 构造 TxOperations。

    失败抛 HulyRestError。

    Args:
        accounts_url: Huly Account RPC URL，如 http://192.168.2.44:8087/_accounts
        admin_email: 管理员邮箱（已有 social id 的账号）
        admin_password: 密码
        workspace_url: workspace URL name（laios）
        timeout: 单次 HTTP 调用超时秒数
    """
    rest = HulyRestClient(accounts_url=accounts_url, timeout=timeout)
    logger.info("[huly] 登录中: email=%s workspace=%s", admin_email, workspace_url)
    user_token = await rest.login(admin_email, admin_password)
    ws = await rest.select_workspace(user_token, workspace_url)
    logger.info(
        "[huly] selectWorkspace 成功: endpoint=%s workspace=%s",
        ws.get("endpoint"),
        ws.get("workspace"),
    )
    account = await rest.get_account()
    logger.info(
        "[huly] getAccount: uuid=%s primarySocialId=%s social_ids=%d",
        account.uuid,
        account.primary_social_id,
        len(account.social_ids),
    )
    ops = TxOperations(rest, account.primary_social_id)
    return HulyPlatformClient(rest=rest, account=account, ops=ops)
