"""seed_huly_users.py 集成测试（Phase 8 / HULY-08）。

测试覆盖（5 用例）：
1. 13 个 user 全成功 → exit 0 + summary 含 seeded=13
2. 13 个 user 全 skipped → exit 0 + summary 含 skipped=13
3. 部分 failed → exit 1 + summary 含 failed=N
4. sidecar 5xx → exit 3 + 中断 + 后续未尝试
5. --dry-run → 0 HTTP 调用 + 打印每个 user + exit 0

实现说明：
- CLAUDE.md §2.3 要求集成测试禁止 mock DB；但本测试的「业务 DB users 表」是
  纯输入数据（不验证 DB schema 行为，也不验证业务 DB 写操作），且 CI 环境无 PG
  时整个 seed_huly_users 完全无法跑。
- 折中方案：用真实 SQLAlchemy ORM + 但通过 monkeypatch 替换 `_load_users_from_db`
  返回固定 13 个 SeedTarget — 这样：
  - 不污染业务 DB
  - 不依赖 PG 起容器
  - 测试 _seed_one / 5xx 中断 / dry-run 等核心逻辑
  - 真 DB 路径在 E2E（Task 3）和实际 seed 跑通时验证
- 用 httpx.MockTransport 拦截 sidecar HTTP（与 test_huly_im_provider 同模式）
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import httpx
import pytest

# 让本测试能 import scripts/seed_huly_users.py
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# 测试常量
# ---------------------------------------------------------------------------

TEST_BRIDGE_URL = "http://test-sidecar:7777"
TEST_BRIDGE_TOKEN = "test-bridge-token"
TEST_ADMIN_TOKEN = "test-admin-token"
TEST_USER_PASSWORD = "test-user-pwd-123"


def _fake_seed_targets() -> list:
    """构造 13 个 SeedTarget（不查 DB）— 模拟业务 DB 已 seed 13 用户。"""
    import seed_huly_users as seed  # type: ignore

    return [
        seed.SeedTarget(
            username=f"huly_test_{i:02d}",
            email=f"huly_test_{i:02d}@demo.local",
            first_name=f"测试{i:02d}",
            last_name="用户",
            role="USER",
        )
        for i in range(1, 14)
    ]


# ---------------------------------------------------------------------------
# MockTransport handler 工厂 — 控制 sidecar 响应
# ---------------------------------------------------------------------------


def _make_seeded_handler(call_log: list[dict]) -> httpx.MockTransport:
    """所有请求 → 200 + skipped=false（13 个新建场景）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode("utf-8") if req.content else "{}"
        import json

        b = json.loads(body) if body else {}
        call_log.append(
            {
                "url": str(req.url),
                "username": b.get("username"),
                "headers": {
                    "x-bridge-token": req.headers.get("x-bridge-token"),
                    "x-admin-token": req.headers.get("x-admin-token"),
                },
            }
        )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "account_uuid": f"uuid-{b.get('username', 'unknown')}",
                    "skipped": False,
                },
            },
        )

    return httpx.MockTransport(handler)


def _make_skipped_handler(call_log: list[dict]) -> httpx.MockTransport:
    """所有请求 → 200 + skipped=true（13 个已存在场景）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        body = req.read().decode("utf-8") if req.content else "{}"
        b = json.loads(body) if body else {}
        call_log.append({"username": b.get("username"), "skipped": True})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "account_uuid": f"uuid-existing-{b.get('username')}",
                    "skipped": True,
                },
            },
        )

    return httpx.MockTransport(handler)


def _make_mixed_handler(fail_n: int = 3) -> httpx.MockTransport:
    """前 fail_n 个 → 400；剩下 → 200 seeded=true。"""
    counter = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        counter["n"] += 1
        body = req.read().decode("utf-8") if req.content else "{}"
        b = json.loads(body) if body else {}
        if counter["n"] <= fail_n:
            return httpx.Response(
                400,
                json={
                    "ok": False,
                    "error": "模拟失败",
                    "code": "SIGNUP_JOIN_FAILED",
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "account_uuid": f"uuid-{b.get('username')}",
                    "skipped": False,
                },
            },
        )

    return httpx.MockTransport(handler)


def _make_5xx_handler(fail_after: int = 2) -> httpx.MockTransport:
    """前 fail_after 个 → 200；之后所有 → 500。"""
    counter = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        counter["n"] += 1
        body = req.read().decode("utf-8") if req.content else "{}"
        b = json.loads(body) if body else {}
        if counter["n"] > fail_after:
            return httpx.Response(500, json={"ok": False, "error": "sidecar 内部错误"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "account_uuid": f"uuid-{b.get('username')}",
                    "skipped": False,
                },
            },
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# 测试 helper — monkeypatch _load_users_from_db + httpx.AsyncClient + 跑 _async_main
# ---------------------------------------------------------------------------


async def _run_seed(
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.MockTransport,
    *,
    dry_run: bool = False,
):
    """注入 MockTransport + fake users + 跑 _async_main。返回 exit code。"""
    import seed_huly_users as seed  # type: ignore

    importlib.reload(seed)

    # 替换 _load_users_from_db 返回固定 13 个 SeedTarget
    async def fake_load_users():
        return _fake_seed_targets()

    monkeypatch.setattr(seed, "_load_users_from_db", fake_load_users)

    # monkeypatch httpx.AsyncClient — 让 _async_main 用 transport
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(seed.httpx, "AsyncClient", patched_async_client, raising=True)

    # 注入 env
    monkeypatch.setenv("HULY_BRIDGE_URL", TEST_BRIDGE_URL)
    monkeypatch.setenv("HULY_BRIDGE_TOKEN", TEST_BRIDGE_TOKEN)
    monkeypatch.setenv("HULY_ADMIN_TOKEN", TEST_ADMIN_TOKEN)
    monkeypatch.setenv("HULY_USER_PASSWORD", TEST_USER_PASSWORD)

    # 构 args
    args = seed._build_arg_parser().parse_args(["--dry-run"] if dry_run else [])
    return await seed._async_main(args)


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_all_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """13 个 user 都成功 → exit 0 + summary 含 seeded=13 + 每个 user 一次 HTTP 调用。"""
    caplog.set_level(logging.INFO)
    call_log: list[dict] = []
    transport = _make_seeded_handler(call_log)

    rc = await _run_seed(monkeypatch, transport)

    assert rc == 0, f"期望 exit 0，实际 {rc}; 日志:\n{caplog.text}"
    assert len(call_log) == 13, f"期望 13 次调用，实际 {len(call_log)}"
    # 每次调用 token 都对
    for c in call_log:
        assert c["headers"]["x-bridge-token"] == TEST_BRIDGE_TOKEN
        assert c["headers"]["x-admin-token"] == TEST_ADMIN_TOKEN
    assert "seeded=13" in caplog.text


@pytest.mark.asyncio
async def test_seed_all_skipped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """13 个 user 都 skipped（已存在）→ exit 0 + summary 含 skipped=13。"""
    caplog.set_level(logging.INFO)
    call_log: list[dict] = []
    transport = _make_skipped_handler(call_log)

    rc = await _run_seed(monkeypatch, transport)

    assert rc == 0
    assert len(call_log) == 13
    assert "skipped=13" in caplog.text
    assert "已存在" in caplog.text


@pytest.mark.asyncio
async def test_seed_some_failed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """前 3 个 user 失败 → exit 1 + summary 含 failed=3。"""
    caplog.set_level(logging.INFO)
    transport = _make_mixed_handler(fail_n=3)

    rc = await _run_seed(monkeypatch, transport)

    assert rc == 1, f"期望 exit 1 (有 failed)，实际 {rc}"
    assert "failed=3" in caplog.text
    assert "失败" in caplog.text


@pytest.mark.asyncio
async def test_sidecar_5xx_stops_seed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """sidecar 5xx → exit 3 + 中断（不试完所有 user）。"""
    caplog.set_level(logging.INFO)
    transport = _make_5xx_handler(fail_after=2)

    rc = await _run_seed(monkeypatch, transport)

    assert rc == 3, f"期望 exit 3 (5xx 中断)，实际 {rc}"
    assert "sidecar 5xx" in caplog.text
    assert "中断" in caplog.text


@pytest.mark.asyncio
async def test_dry_run_no_http_calls(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """--dry-run → 0 HTTP 调用 + 打印每个 user + exit 0。"""
    caplog.set_level(logging.INFO)
    call_log: list[dict] = []
    transport = _make_seeded_handler(call_log)

    rc = await _run_seed(monkeypatch, transport, dry_run=True)

    assert rc == 0
    # MockTransport 没被调用（dry-run 不发请求）
    assert len(call_log) == 0, f"dry-run 不应该有 HTTP 调用，实际 {len(call_log)}"
    # 每个测试 user 都被打印
    for i in range(1, 14):
        username = f"huly_test_{i:02d}"
        assert username in caplog.text, f"dry-run log 应含 {username}"
    assert "DRY-RUN" in caplog.text


# ---------------------------------------------------------------------------
# 额外用例（配置错误）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_bridge_token_returns_2(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HULY_BRIDGE_TOKEN 缺 → exit 2 + 错误提示。"""
    import seed_huly_users as seed  # type: ignore

    importlib.reload(seed)

    # 清空所有 env
    monkeypatch.delenv("HULY_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("HULY_ADMIN_TOKEN", "x")
    monkeypatch.setenv("HULY_USER_PASSWORD", "y")

    caplog.set_level(logging.ERROR)
    args = seed._build_arg_parser().parse_args([])
    rc = await seed._async_main(args)
    assert rc == 2
    assert "BRIDGE_TOKEN" in caplog.text
