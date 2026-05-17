"""IMListener Protocol 单元测试（ABS-01 / ABS-04）。

覆盖：
1. 完整实现的 MockListener → isinstance(.., IMListener) is True
2. 缺 register_command_listener 的实现 → isinstance(.., IMListener) is False
3. DispatchFn 类型别名导入可用 + 可被赋值
4. IMHelpers 是 frozen dataclass — 不可变性校验
"""

from __future__ import annotations

import dataclasses

import pytest

from offboarding_flow.im.context import IMHelpers
from offboarding_flow.im.protocol import DispatchFn, IMListener


class _FullMockListener:
    """完整实现 IMListener 全部成员的最小 mock。"""

    name: str = "mock"

    def __init__(self) -> None:
        self._dispatch: DispatchFn | None = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        self._dispatch = dispatch


class _BrokenMockListener:
    """故意缺 register_command_listener 的实现 — 应被 runtime_checkable 拒绝。"""

    name: str = "broken"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def test_full_mock_listener_satisfies_protocol() -> None:
    """完整实现 4 个成员（含 name attribute）应通过 isinstance 检查。"""
    listener = _FullMockListener()
    assert isinstance(listener, IMListener), "完整实现应满足 IMListener Protocol"


def test_broken_mock_missing_register_fails_protocol_check() -> None:
    """缺 register_command_listener 的实现应被 runtime_checkable 拒绝。"""
    listener = _BrokenMockListener()
    assert not isinstance(listener, IMListener), "缺关键方法的实现不应满足 IMListener Protocol"


def test_dispatch_fn_type_alias_is_importable_and_assignable() -> None:
    """DispatchFn 是 Callable[..., Awaitable[None]] 类型别名，可被赋值。"""

    async def _noop(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    fn: DispatchFn = _noop
    assert callable(fn)


async def _dummy_post(channel_id: str, msg: str) -> None:
    return None


async def _dummy_dm(username: str, msg: str) -> None:
    return None


def test_im_helpers_is_frozen_dataclass() -> None:
    """IMHelpers 应是 frozen dataclass，赋值字段会抛 FrozenInstanceError。"""
    helpers = IMHelpers(post_channel=_dummy_post, send_dm=_dummy_dm)
    assert dataclasses.is_dataclass(helpers)

    with pytest.raises(dataclasses.FrozenInstanceError):
        helpers.post_channel = _dummy_dm  # type: ignore[misc]


def test_im_helpers_ensure_in_channel_optional() -> None:
    """ensure_in_channel 默认 None 时构造应成功（HulyCard 等无 channel 平台用）。"""
    helpers = IMHelpers(post_channel=_dummy_post, send_dm=_dummy_dm)
    assert helpers.ensure_in_channel is None
