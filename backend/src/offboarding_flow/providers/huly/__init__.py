"""Huly 平台 Python SDK — REST 直连模式（Phase 8 B-full 重构）。

复刻 @hcengineering/api-client 的 PlatformClient 接口，去除 huly-bridge sidecar。

模块结构：
- constants.py   — Huly 模型 class id / space id 字符串常量
- rest_client.py — 7 REST endpoint + Account RPC 封装
- tx_factory.py  — Tx 对象工厂（复刻 TS TxFactory）
- tx_operations.py — TxOperations facade（createDoc/addCollection/...）
- platform_client.py — connect/login + 串联以上

import 入口（与 sidecar 调用对齐）：
    from offboarding_flow.providers.huly import HulyPlatformClient, connect_huly
"""

from __future__ import annotations

from .constants import (
    CHUNTER_CLASS_CHANNEL,
    CHUNTER_CLASS_CHAT_MESSAGE,
    CHUNTER_CLASS_DIRECT_MESSAGE,
    CONTACT_CLASS_PERSON,
    CONTACT_CLASS_SOCIAL_IDENTITY,
    CONTACT_MIXIN_EMPLOYEE,
    CORE_CLASS_TX_CREATE_DOC,
    CORE_CLASS_TX_MIXIN,
    CORE_CLASS_TX_REMOVE_DOC,
    CORE_CLASS_TX_UPDATE_DOC,
    CORE_SPACE_SPACE,
    CORE_SPACE_TX,
    DEMO_EMAIL_DOMAIN,
    DOCUMENT_CLASS_DOCUMENT,
    DOCUMENT_CLASS_TEAMSPACE,
    DOCUMENT_IDS_NO_PARENT,
    DOCUMENT_TYPE_DEFAULT,
)
from .platform_client import HulyPlatformClient, connect_huly
from .rest_client import AccountInfo, HulyRestClient
from .tx_factory import TxFactory, generate_id
from .tx_operations import TxOperations

__all__ = [
    "AccountInfo",
    "CHUNTER_CLASS_CHANNEL",
    "CHUNTER_CLASS_CHAT_MESSAGE",
    "CHUNTER_CLASS_DIRECT_MESSAGE",
    "CONTACT_CLASS_PERSON",
    "CONTACT_CLASS_SOCIAL_IDENTITY",
    "CONTACT_MIXIN_EMPLOYEE",
    "CORE_CLASS_TX_CREATE_DOC",
    "CORE_CLASS_TX_MIXIN",
    "CORE_CLASS_TX_REMOVE_DOC",
    "CORE_CLASS_TX_UPDATE_DOC",
    "CORE_SPACE_SPACE",
    "CORE_SPACE_TX",
    "DEMO_EMAIL_DOMAIN",
    "DOCUMENT_CLASS_DOCUMENT",
    "DOCUMENT_CLASS_TEAMSPACE",
    "DOCUMENT_IDS_NO_PARENT",
    "DOCUMENT_TYPE_DEFAULT",
    "HulyPlatformClient",
    "HulyRestClient",
    "TxFactory",
    "TxOperations",
    "connect_huly",
    "generate_id",
]
