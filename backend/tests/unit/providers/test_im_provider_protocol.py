"""IMProvider Protocol 单元测试（ABS-04 — register_command_listener hook）。

覆盖：
1. MattermostProvider / LarkIMProvider / WeComIMProvider / DingTalkIMProvider
   全部满足扩展后的 IMProvider Protocol（含 register_command_listener）
2. 缺 register_command_listener 的实现 → isinstance 检查应失败
3. register_command_listener 调用后 _dispatch 字段正确保存
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.providers import IMProvider
from offboarding_flow.providers.dingtalk_provider import DingTalkIMProvider
from offboarding_flow.providers.wecom_provider import WeComIMProvider


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """stub Settings 避免读 .env / 验证字段。"""
    fake = MagicMock()
    fake.mattermost_url = "http://mm:8065"
    fake.mattermost_bot_token = "fake-token"
    fake.mattermost_bot_user_id = "bot_id"
    fake.mattermost_http_timeout = 10
    fake.lark_base_url = "https://open.feishu.cn"
    fake.lark_app_id = "cli_demo"
    fake.lark_app_secret = "sec_demo"
    fake.lark_docs_folder_token = "folder_root"
    monkeypatch.setattr("offboarding_flow.providers.mattermost_provider.get_settings", lambda: fake)
    monkeypatch.setattr("offboarding_flow.providers.lark_provider.get_settings", lambda: fake)


def test_mattermost_provider_satisfies_extended_im_protocol() -> None:
    """MattermostProvider 必须满足含 register_command_listener 的扩展 Protocol。"""
    from offboarding_flow.providers.mattermost_provider import MattermostProvider

    provider = MattermostProvider()
    assert isinstance(
        provider, IMProvider
    ), "MattermostProvider 必须满足扩展后的 IMProvider Protocol（含 ABS-04 hook）"


def test_lark_im_provider_satisfies_extended_im_protocol() -> None:
    """LarkIMProvider 必须满足含 register_command_listener 的扩展 Protocol。"""
    from offboarding_flow.providers.lark_provider import LarkIMProvider

    provider = LarkIMProvider()
    assert isinstance(
        provider, IMProvider
    ), "LarkIMProvider 必须满足扩展后的 IMProvider Protocol（含 ABS-04 hook）"


def test_wecom_im_provider_satisfies_extended_im_protocol() -> None:
    """WeComIMProvider stub 必须满足扩展 Protocol。"""
    provider = WeComIMProvider()
    assert isinstance(provider, IMProvider)


def test_dingtalk_im_provider_satisfies_extended_im_protocol() -> None:
    """DingTalkIMProvider stub 必须满足扩展 Protocol。"""
    provider = DingTalkIMProvider()
    assert isinstance(provider, IMProvider)


def test_im_provider_protocol_rejects_partial_impl() -> None:
    """缺 register_command_listener 的实现 → runtime_checkable 拒绝。"""

    class _IncompleteIMProvider:
        name = "incomplete"

        async def post_to_channel(self, channel_id, markdown):
            return None

        async def send_dm(self, username, markdown):
            return None

        async def ensure_user_in_channel(self, channel_id, username):
            return None

        async def list_team_users(self):
            return []

        async def resolve_username(self, username):
            return None

        # 故意缺：register_command_listener

    provider = _IncompleteIMProvider()
    assert not isinstance(provider, IMProvider), "缺 ABS-04 hook 的实现应被 Protocol 拒绝"


def test_register_command_listener_saves_dispatch_reference() -> None:
    """register_command_listener 调用后 _dispatch 字段应保存传入的 callable。"""
    from offboarding_flow.providers.mattermost_provider import MattermostProvider

    provider = MattermostProvider()
    fake_dispatch = AsyncMock()

    provider.register_command_listener(fake_dispatch)

    assert provider._dispatch is fake_dispatch


def test_register_command_listener_on_stub_providers_works() -> None:
    """stub provider 的 register_command_listener 也应正确保存 dispatch。"""
    wecom = WeComIMProvider()
    dingtalk = DingTalkIMProvider()
    fake_dispatch = AsyncMock()

    wecom.register_command_listener(fake_dispatch)
    dingtalk.register_command_listener(fake_dispatch)

    assert wecom._dispatch is fake_dispatch
    assert dingtalk._dispatch is fake_dispatch
