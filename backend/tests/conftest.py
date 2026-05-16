"""Pytest 全局 fixture 与配置。

约定（PITFALLS #23）：
- asyncio mode=auto + loop_scope=session（在 pyproject.toml 配置）
- 避免每个测试用例创建新 event loop 导致 SQLAlchemy async engine 共享冲突

后续 Plan 03 / 04 / 06 会扩充 db / graph / client fixture。
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """显式声明事件循环策略，避免不同平台行为差异。"""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """如果有 anyio 测试，固定为 asyncio。"""
    return "asyncio"
