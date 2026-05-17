"""DocProvider Protocol 单元测试（ABS-03）。

覆盖：
1. OutlineProvider / LarkDocsProvider / WeComDocProvider / DingTalkDocProvider
   全部满足扩展后的 DocProvider Protocol（含 delete_document /
   list_documents_in_collection / delete_collection）
2. CollectionInfo 是 frozen dataclass
3. 缺方法的 stub class → isinstance 检查应失败
"""

from __future__ import annotations

import dataclasses

from offboarding_flow.providers import CollectionInfo, DocProvider
from offboarding_flow.providers.dingtalk_provider import DingTalkDocProvider
from offboarding_flow.providers.outline_provider import OutlineProvider
from offboarding_flow.providers.wecom_provider import WeComDocProvider


def test_outline_provider_satisfies_extended_doc_protocol() -> None:
    """OutlineProvider 满足含 3 个新生命周期方法的 DocProvider Protocol。"""
    provider = OutlineProvider(client=None)
    assert isinstance(
        provider, DocProvider
    ), "OutlineProvider 必须满足扩展后的 DocProvider Protocol（含 ABS-03 3 方法）"


def test_lark_provider_satisfies_extended_doc_protocol() -> None:
    """LarkDocsProvider 满足含 3 个新生命周期方法的 DocProvider Protocol。"""
    # 直接 import — 不实例化（构造需要 settings；只检查类层面 Protocol 兼容）
    from offboarding_flow.providers.lark_provider import LarkDocsProvider

    # 检查类拥有 3 个新方法（无需实例化）
    assert hasattr(LarkDocsProvider, "delete_document")
    assert hasattr(LarkDocsProvider, "list_documents_in_collection")
    assert hasattr(LarkDocsProvider, "delete_collection")


def test_wecom_provider_satisfies_extended_doc_protocol() -> None:
    """WeComDocProvider stub 也必须满足新 Protocol（避免破坏未来切换）。"""
    provider = WeComDocProvider()
    assert isinstance(provider, DocProvider), "WeComDocProvider stub 应满足扩展后 Protocol"


def test_dingtalk_provider_satisfies_extended_doc_protocol() -> None:
    """DingTalkDocProvider stub 也必须满足新 Protocol。"""
    provider = DingTalkDocProvider()
    assert isinstance(provider, DocProvider), "DingTalkDocProvider stub 应满足扩展后 Protocol"


def test_collection_info_is_frozen_dataclass() -> None:
    """CollectionInfo 是 frozen dataclass — 不可变。"""
    info = CollectionInfo(id="col1", name="测试 collection", provider="outline")
    assert dataclasses.is_dataclass(info)
    assert info.id == "col1"
    assert info.name == "测试 collection"
    assert info.provider == "outline"

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.name = "新名字"  # type: ignore[misc]


def test_doc_provider_protocol_rejects_partial_impl() -> None:
    """缺少新生命周期方法的实现 → runtime_checkable 拒绝。"""

    class _IncompleteDocProvider:
        name = "incomplete"

        async def create_document(self, *, title, markdown, owner_usernames=None):
            return None  # type: ignore

        async def update_document(self, *, doc_id, markdown, title=None):
            return None

        async def list_documents(self, *, query=None, limit=10):
            return []

        async def ensure_users(self, users):
            return {"created": [], "skipped": []}

        async def get_document(self, doc_id):
            return None

        # 故意缺：delete_document / list_documents_in_collection / delete_collection

    provider = _IncompleteDocProvider()
    assert not isinstance(provider, DocProvider), "缺少 3 个新方法的实现应被 Protocol 拒绝"
