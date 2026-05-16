"""E2E 测试通用 fixture：app_client。

CLAUDE.md §2.1：每个 phase 完成后必须跑全流程 E2E。

支持两种模式：
1. OFFBOARDING_E2E_BASE_URL 指向运行中的容器 — 走 HTTP
2. TEST_DATABASE_URL 设置 — inline ASGI + 真 PG

两者都没设置 → skip e2e（CI 上可单独跑 e2e job 时设置）。
"""

from __future__ import annotations

import os

import httpx
import pytest

_BASE_URL = os.environ.get("OFFBOARDING_E2E_BASE_URL")
_TEST_DSN = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def app_client():
    """优先用 OFFBOARDING_E2E_BASE_URL 打真容器；否则 inline ASGI。"""
    if _BASE_URL:
        async with httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
            yield ac
        return

    if not _TEST_DSN:
        pytest.skip("需要 OFFBOARDING_E2E_BASE_URL 或 TEST_DATABASE_URL 启动 E2E")

    # inline ASGI 模式 — 需要真 PG（CLAUDE.md §2.3 禁止 mock DB）
    from asgi_lifespan import LifespanManager

    from offboarding_flow.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as ac:
            yield ac
