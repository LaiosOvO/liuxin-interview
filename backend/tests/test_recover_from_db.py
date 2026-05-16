"""test_recover_from_db.py — scripts/recover_from_db CLI 单测（Phase 2 Plan 01）。

测试策略：
- 用 MagicMock 替换 graph + new_session（不接真 PG / 真 graph 单例）
- 覆盖：dry-run / 成功恢复 / 持续失败 / max_retries
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scripts.recover_from_db import recover_all

from offboarding_flow.state_store.enums import ActionStatus


def _make_failed_action(action_id=None, action="advance", actor="tester"):
    """构造一条 fake failed action_log。"""
    m = MagicMock()
    m.id = action_id or uuid.uuid4()
    m.flow_id = uuid.uuid4()
    m.action = action
    m.result_text = "test"
    m.actor = actor
    m.status = ActionStatus.FAILED.value
    return m


def _mock_session_factory_returning(failed_list):
    """构造一个 mock new_session 上下文管理器：list_failed → failed_list；mark_success → no-op。"""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        session_mock = MagicMock()
        session_mock.commit = AsyncMock()
        yield session_mock

    return _ctx


@pytest.fixture
def mock_graph():
    """提供一个 mock graph，ainvoke 默认 success（测试可在用例内 patch 抛错）。"""
    g = MagicMock()
    g.ainvoke = AsyncMock(return_value=None)
    return g


async def test_recover_dry_run_does_not_invoke_graph(mock_graph):
    """dry-run 模式不应调 graph.ainvoke。"""
    failed = [_make_failed_action(), _make_failed_action()]

    # patch ActionRepository.list_failed 返回 failed
    with (
        patch("scripts.recover_from_db.new_session") as ns_patch,
        patch("scripts.recover_from_db.ActionRepository") as ar_patch,
    ):
        # new_session 返回的 context manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_ns():
            yield MagicMock(commit=AsyncMock())

        ns_patch.return_value = _fake_ns()

        # ActionRepository(session) 返回带 list_failed / mark_success
        repo_instance = MagicMock()
        repo_instance.list_failed = AsyncMock(return_value=failed)
        repo_instance.mark_success = AsyncMock()
        ar_patch.return_value = repo_instance

        stats = await recover_all(
            flow_id=None,
            dry_run=True,
            max_retries=3,
            graph=mock_graph,
        )

    assert stats["scanned"] == 2
    assert stats["recovered"] == 0  # dry-run 不算 recovered
    assert mock_graph.ainvoke.await_count == 0


async def test_recover_marks_success_when_graph_succeeds(mock_graph):
    """单条 failed action_log → graph.ainvoke 成功 → mark_success + recovered += 1。"""
    failed = [_make_failed_action()]

    mark_success_calls = []

    with (
        patch("scripts.recover_from_db.new_session") as ns_patch,
        patch("scripts.recover_from_db.ActionRepository") as ar_patch,
    ):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_ns():
            yield MagicMock(commit=AsyncMock())

        ns_patch.side_effect = lambda: _fake_ns()

        async def _mark_success(action_id):
            mark_success_calls.append(action_id)

        repo_instance = MagicMock()
        repo_instance.list_failed = AsyncMock(return_value=failed)
        repo_instance.mark_success = _mark_success
        ar_patch.return_value = repo_instance

        stats = await recover_all(flow_id=None, dry_run=False, max_retries=3, graph=mock_graph)

    assert stats["scanned"] == 1
    assert stats["recovered"] == 1
    assert stats["still_failed"] == 0
    assert mock_graph.ainvoke.await_count == 1
    assert mark_success_calls == [failed[0].id]


async def test_recover_increments_retry_when_graph_keeps_failing(mock_graph):
    """graph 持续抛 → still_failed 累加，不死循环。"""
    failed = [_make_failed_action()]

    # 让 graph.ainvoke 抛
    mock_graph.ainvoke = AsyncMock(side_effect=ConnectionError("simulated"))

    with (
        patch("scripts.recover_from_db.new_session") as ns_patch,
        patch("scripts.recover_from_db.ActionRepository") as ar_patch,
    ):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_ns():
            yield MagicMock(commit=AsyncMock())

        ns_patch.side_effect = lambda: _fake_ns()

        repo_instance = MagicMock()
        repo_instance.list_failed = AsyncMock(return_value=failed)
        repo_instance.mark_success = AsyncMock()
        ar_patch.return_value = repo_instance

        stats = await recover_all(flow_id=None, dry_run=False, max_retries=3, graph=mock_graph)

    assert stats["scanned"] == 1
    assert stats["recovered"] == 0
    assert stats["still_failed"] == 1
    # graph.ainvoke 应被调过 1 次（list_failed 只返回 1 条；max_retries 是 in-memory 计数，
    # 单轮扫描每条只 invoke 1 次）
    assert mock_graph.ainvoke.await_count == 1


async def test_recover_filters_by_flow_id(mock_graph):
    """传入 flow_id 应过滤到 list_failed。"""
    target_flow = uuid.uuid4()

    with (
        patch("scripts.recover_from_db.new_session") as ns_patch,
        patch("scripts.recover_from_db.ActionRepository") as ar_patch,
    ):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_ns():
            yield MagicMock(commit=AsyncMock())

        ns_patch.return_value = _fake_ns()

        list_failed_mock = AsyncMock(return_value=[])
        repo_instance = MagicMock()
        repo_instance.list_failed = list_failed_mock
        ar_patch.return_value = repo_instance

        await recover_all(flow_id=target_flow, dry_run=True, max_retries=3, graph=mock_graph)

    # list_failed 必须用 flow_id=target_flow 调
    call_kwargs = list_failed_mock.await_args.kwargs
    assert call_kwargs.get("flow_id") == target_flow


def test_recover_main_cli_help_runnable(capsys):
    """argparse 应输出 --help 信息（验证 CLI 可执行 + 不引入新依赖）。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "scripts.recover_from_db", "--help"],
        capture_output=True,
        text=True,
        cwd="/Users/admin/ai/resume/interview/liuxin/hr/.claude/worktrees/phase-2-offboarding/backend",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "--flow-id" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--max-retries" in result.stdout
