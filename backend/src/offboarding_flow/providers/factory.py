"""Provider 工厂 — 按 settings.doc_provider / settings.im_provider 选择实现。"""

from __future__ import annotations

import logging
from functools import lru_cache

from offboarding_flow.config import get_settings

from .base import DocProvider, IMProvider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_doc_provider() -> DocProvider:
    settings = get_settings()
    name = (settings.doc_provider or "outline").lower()
    logger.info("[providers] using doc provider: %s", name)
    if name == "outline":
        from .outline_provider import OutlineProvider

        return OutlineProvider()
    if name == "lark":
        from .lark_provider import LarkDocsProvider

        return LarkDocsProvider()
    if name == "wecom":
        from .wecom_provider import WeComDocProvider

        return WeComDocProvider()
    if name == "dingtalk":
        from .dingtalk_provider import DingTalkDocProvider

        return DingTalkDocProvider()
    raise ValueError(f"未知 DOC_PROVIDER: {name}")


@lru_cache(maxsize=1)
def get_im_provider() -> IMProvider:
    settings = get_settings()
    name = (settings.im_provider or "mattermost").lower()
    logger.info("[providers] using im provider: %s", name)
    if name == "mattermost":
        from .mattermost_provider import MattermostProvider

        return MattermostProvider()
    if name == "lark":
        from .lark_provider import LarkIMProvider

        return LarkIMProvider()
    if name == "wecom":
        from .wecom_provider import WeComIMProvider

        return WeComIMProvider()
    if name == "dingtalk":
        from .dingtalk_provider import DingTalkIMProvider

        return DingTalkIMProvider()
    raise ValueError(f"未知 IM_PROVIDER: {name}")


def reset_providers() -> None:
    """测试用：清单例缓存。"""
    get_doc_provider.cache_clear()
    get_im_provider.cache_clear()
