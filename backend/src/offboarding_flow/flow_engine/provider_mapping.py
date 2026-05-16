"""离职流程状态机内 节点 ↔ Provider 路由 mapping。

设计：
- 默认全局走 settings.doc_provider / settings.im_provider
- 部分节点 / 部分角色可以"覆写"到特定 Provider（如 IT 节点走钉钉，财务走企微）
- 表驱动：改 dict 即生效，无需改逻辑代码
- 实际生产可挪到 DB 表方便运维改

使用：
    from offboarding_flow.flow_engine.provider_mapping import resolve_doc_provider, resolve_im_provider
    doc = resolve_doc_provider(node_name="device_return", actor_role="it_admin")
"""

from __future__ import annotations

import logging

from offboarding_flow.providers import (
    DocProvider,
    IMProvider,
    get_doc_provider,
    get_im_provider,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 节点 / 角色 → Provider 覆写表（None 表示走全局默认）
# ---------------------------------------------------------------------------
#
# 维护规则：
# - key 是 node_name（如 "device_return"）或 role（如 "it_admin"）
# - value 是 Provider 名（"outline" / "lark" / "wecom" / "dingtalk" / "mattermost"）
# - 优先级：node-level > role-level > settings 全局默认
#
# 当前 demo 场景全走默认（Outline + Mattermost）；接入飞书/企微/钉钉时把对应 key 配上即可。

NODE_DOC_OVERRIDES: dict[str, str] = {
    # "device_return": "lark",        # 假设 IT 部门用飞书 wiki
    # "finance_settle": "wecom",      # 假设财务用企微文档
    # "knowledge_handover": "lark",   # 知识库用飞书
}

ROLE_DOC_OVERRIDES: dict[str, str] = {
    # "it_admin": "lark",
    # "finance": "wecom",
    # "legal": "lark",
}

NODE_IM_OVERRIDES: dict[str, str] = {
    # "device_return": "dingtalk",     # IT 群在钉钉
    # "manager_review": "lark",        # 管理层在飞书
}

ROLE_IM_OVERRIDES: dict[str, str] = {
    # "manager": "lark",               # manager 用飞书
    # "it_admin": "dingtalk",          # IT 用钉钉
}


def resolve_doc_provider(
    *, node_name: str | None = None, actor_role: str | None = None
) -> DocProvider:
    """按节点 / 角色路由 DocProvider，找不到走全局默认。"""
    target_name: str | None = None
    if node_name and node_name in NODE_DOC_OVERRIDES:
        target_name = NODE_DOC_OVERRIDES[node_name]
        logger.debug("[provider_mapping] doc node-override %s -> %s", node_name, target_name)
    elif actor_role and actor_role in ROLE_DOC_OVERRIDES:
        target_name = ROLE_DOC_OVERRIDES[actor_role]
        logger.debug("[provider_mapping] doc role-override %s -> %s", actor_role, target_name)

    if target_name:
        return _build_doc_provider_by_name(target_name)
    return get_doc_provider()


def resolve_im_provider(
    *, node_name: str | None = None, actor_role: str | None = None
) -> IMProvider:
    """按节点 / 角色路由 IMProvider，找不到走全局默认。"""
    target_name: str | None = None
    if node_name and node_name in NODE_IM_OVERRIDES:
        target_name = NODE_IM_OVERRIDES[node_name]
    elif actor_role and actor_role in ROLE_IM_OVERRIDES:
        target_name = ROLE_IM_OVERRIDES[actor_role]

    if target_name:
        return _build_im_provider_by_name(target_name)
    return get_im_provider()


def _build_doc_provider_by_name(name: str) -> DocProvider:
    """按名字构造一个 DocProvider 实例（不走 lru_cache，避免污染全局单例）。"""
    name = name.lower()
    if name == "outline":
        from offboarding_flow.providers.outline_provider import OutlineProvider

        return OutlineProvider()
    if name == "lark":
        from offboarding_flow.providers.lark_provider import LarkDocsProvider

        return LarkDocsProvider()
    if name == "wecom":
        from offboarding_flow.providers.wecom_provider import WeComDocProvider

        return WeComDocProvider()
    if name == "dingtalk":
        from offboarding_flow.providers.dingtalk_provider import (
            DingTalkDocProvider,
        )

        return DingTalkDocProvider()
    raise ValueError(f"未知 doc provider: {name}")


def _build_im_provider_by_name(name: str) -> IMProvider:
    name = name.lower()
    if name == "mattermost":
        from offboarding_flow.providers.mattermost_provider import (
            MattermostProvider,
        )

        return MattermostProvider()
    if name == "lark":
        from offboarding_flow.providers.lark_provider import LarkIMProvider

        return LarkIMProvider()
    if name == "wecom":
        from offboarding_flow.providers.wecom_provider import WeComIMProvider

        return WeComIMProvider()
    if name == "dingtalk":
        from offboarding_flow.providers.dingtalk_provider import (
            DingTalkIMProvider,
        )

        return DingTalkIMProvider()
    raise ValueError(f"未知 im provider: {name}")
