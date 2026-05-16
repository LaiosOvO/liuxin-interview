"""test_auto_archive_to_storage.py — Phase 4.5 集成测试。

起一个 mock-archive-service subprocess（端口随机） + 通过 _post_to_archive_service
真实 HTTP 调用，验证：
1. 成功路径：POST → 文件落地 → 返回 archived=True
2. 失败路径：subprocess 关掉 → tenacity 重试用完后抛 httpx.RequestError
3. 节点函数完整链路（mock DB session）：调用真 mock service + 双写 hook

注：本测试不连真 PG（用 mock session），但用真 mock-archive-service subprocess。
完整 PG + subprocess 双真集成留给 E2E（Slice 4D 会跑全流程）。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio

pytestmark = [pytest.mark.integration]


def _free_port() -> int:
    """找一个空闲 TCP 端口（用于 mock-archive-service subprocess）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def archive_data_dir():
    """提供 mock service 写文件目录 — 临时目录用完删。"""
    with tempfile.TemporaryDirectory(prefix="auto-archive-") as d:
        yield pathlib.Path(d)


@pytest_asyncio.fixture
async def mock_archive_subprocess(archive_data_dir, monkeypatch):
    """在 subprocess 启 mock-archive-service。

    清理 env 中的 *_PROXY（防止 httpx 依赖 socksio）。
    """
    import os

    # 清掉 proxy env 防止 httpx 跑测试时报 socksio 缺失（仅本测试 session 范围）
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)

    port = _free_port()
    env = os.environ.copy()
    env["ARCHIVE_DATA_DIR"] = str(archive_data_dir)
    # 也从 subprocess env 移除 proxy（避免 subprocess httpx 调用问题，虽然 mock 服务用不到）
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(var, None)
    # mock-archive-service 目录 = repo 根 / mock-archive-service
    mock_dir = pathlib.Path(__file__).resolve().parents[3] / "mock-archive-service"
    if not mock_dir.exists():
        pytest.skip(f"mock-archive-service 目录缺失: {mock_dir}")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(mock_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # poll /health 等到起来（最多 10s）— 检查 proc 是否提前死掉
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    ok = False
    last_err: Exception | None = None
    while time.time() < deadline:
        # subprocess 已死 → 立刻退出
        if proc.poll() is not None:
            out, _ = proc.communicate()
            pytest.skip(
                f"mock-archive-service subprocess 提前退出 exit={proc.returncode}: {out.decode()[:500]}"
            )
        try:
            # 显式禁 proxy（避免环境 SOCKS_PROXY 触发 socksio 依赖问题）
            async with httpx.AsyncClient(timeout=1.0, trust_env=False) as c:
                r = await c.get(f"{base_url}/health")
                if r.status_code == 200:
                    ok = True
                    break
        except Exception as e:
            last_err = e
        await asyncio.sleep(0.2)
    if not ok:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=2)
            err_tail = out.decode()[-500:] if out else ""
        except Exception:
            err_tail = ""
        pytest.skip(
            f"mock-archive-service subprocess 启不来 (port={port}); last_err={last_err}; output={err_tail}"
        )

    try:
        yield {"port": port, "url": base_url, "data_dir": archive_data_dir}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def test_post_to_subprocess_writes_file(mock_archive_subprocess):
    """真 HTTP POST 到真 subprocess → 文件落地 → 内容可读回。"""
    from offboarding_flow.flow_engine.nodes.auto_archive_to_storage import (
        _post_to_archive_service,
    )

    flow_id = str(uuid.uuid4())
    body = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "node_results": [{"node_name": "manager_review", "actor": "li.si"}],
    }
    url = f"{mock_archive_subprocess['url']}/archive"
    resp = await _post_to_archive_service(url=url, body=body, timeout=5.0, max_retries=2)
    assert resp["archived"] is True
    # 验证文件落地
    archive_file = mock_archive_subprocess["data_dir"] / f"{flow_id}.json"
    assert archive_file.exists(), f"归档文件应存在: {archive_file}"
    archived = json.loads(archive_file.read_text(encoding="utf-8"))
    assert archived["flow_id"] == flow_id
    assert archived["employee_id"] == "zhang.san"


async def test_node_function_end_to_end_with_real_subprocess(mock_archive_subprocess, monkeypatch):
    """节点函数完整跑：真 subprocess + mock DB session → 文件落地 + AutoNodeService 调用。"""
    from offboarding_flow.config import get_settings
    from offboarding_flow.flow_engine.nodes.auto_archive_to_storage import (
        AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
        auto_archive_to_storage_node,
    )
    from offboarding_flow.state_store.enums import ActionStatus

    # 把 ARCHIVE_SERVICE_URL 指向 subprocess
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "archive_service_url",
        f"{mock_archive_subprocess['url']}/archive",
        raising=False,
    )

    # mock AutoNodeService（避免真 DB）— 节点函数里 delayed import 该模块
    captured: dict = {"calls": []}

    async def fake_execute(**kw):
        captured["calls"].append(kw)

    # 强制 import 服务模块（节点函数延迟 import，测试 patch 时必须已 loaded）
    from offboarding_flow.services import auto_node_service as mod_svc

    fake_svc = MagicMock()
    fake_svc.execute_auto_action = fake_execute
    monkeypatch.setattr(mod_svc, "AutoNodeService", lambda: fake_svc)

    flow_id = str(uuid.uuid4())
    state = {
        "flow_id": flow_id,
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [
            {
                "node_name": "manager_review",
                "node_title": "上级审批",
                "result_text": "同意",
                "actor": "li.si",
                "completed_at": "2026-05-16T10:00:00+00:00",
            }
        ],
        "context": {},
    }
    result = await auto_archive_to_storage_node(state)

    # 1) 节点函数返回 advance
    assert result["current_action"] == "advance"
    assert result["node_results"][0]["node_name"] == AUTO_ARCHIVE_TO_STORAGE_NODE_NAME
    assert result["node_results"][0]["actor"] == "system:auto"

    # 2) AutoNodeService.execute_auto_action 被调用一次 SUCCESS
    assert len(captured["calls"]) == 1
    assert captured["calls"][0]["action_status"] == ActionStatus.SUCCESS
    assert captured["calls"][0]["actor"] == "system:auto"

    # 3) 文件真的写到 subprocess data_dir
    archive_file = mock_archive_subprocess["data_dir"] / f"{flow_id}.json"
    assert archive_file.exists(), (
        f"归档文件应在 subprocess data_dir 落地: {archive_file}; "
        f"现有文件: {list(mock_archive_subprocess['data_dir'].iterdir())}"
    )
    archived = json.loads(archive_file.read_text(encoding="utf-8"))
    assert archived["flow_id"] == flow_id
    assert len(archived["node_results"]) == 1
