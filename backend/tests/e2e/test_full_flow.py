"""Phase 1 后端全流程冒烟测试 — 用 httpx 打真后端容器（无 mock）。

默认 skip — 通过 OFFBOARDING_E2E_BASE_URL 环境变量启用：
  export OFFBOARDING_E2E_BASE_URL=http://localhost:8000
  uv run pytest tests/e2e/ -v -m e2e

Phase 2+ 会在本文件追加更多场景（见 README.md）。
"""

from __future__ import annotations

import os

import httpx
import pytest

_BASE_URL = os.environ.get("OFFBOARDING_E2E_BASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _BASE_URL,
        reason="需要 OFFBOARDING_E2E_BASE_URL 环境变量指向运行中的后端容器",
    ),
]


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=_BASE_URL or "", timeout=10.0) as ac:
        yield ac


async def test_health_endpoint_returns_200(client):
    """Phase 1 验收 #1: uvicorn 起来 /api/health 返回 200。"""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] in ("ok", "degraded")


async def test_create_flow_and_advance_full_loop(client):
    """Phase 1 验收 #2+#3+#5: 起流程 + advance + 业务表与 checkpoint 一致。"""
    # Step 1: 起流程
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    flow_id = data["flow_id"]
    node_id = data["current_node"]["id"]
    assert data["current_node"]["name"] == "manager_review"
    assert data["current_node"]["status"] == "waiting_human"

    # Step 2: GET /api/flows/{id}/nodes 校验 apply + manager_review 都在
    resp = await client.get(f"/api/flows/{flow_id}/nodes")
    assert resp.status_code == 200
    names = sorted(n["name"] for n in resp.json()["data"])
    assert names == ["apply", "manager_review"]

    # Step 3: advance manager_review
    resp = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "advance", "result_text": "同意离职", "actor": "li.si"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["new_status"] == "done"

    # Step 4: 重读 — 节点 done 流程 completed
    resp = await client.get(f"/api/flows/{flow_id}")
    assert resp.json()["data"]["status"] == "completed"


@pytest.mark.skip(reason="Phase 1 不强制 — 需手动 docker compose restart flow-api 后调用")
async def test_docker_restart_recovers(client):
    """Phase 1 验收 #4: docker restart 后流程进度无丢失。

    手动验证步骤：
      1. 跑 test_create_flow_and_advance_full_loop 到 Step 2 后暂停
      2. docker compose restart flow-api
      3. 等待 /api/health 200
      4. GET /api/flows/{id} 仍能查到节点状态
      5. POST advance 仍能推进

    自动化版本：留 Phase 2 完整双写规范后实现（需 docker SDK / subprocess 控制）。
    """
    # 占位实现 — Phase 2 才完善


# Phase 2+ 用例占位（这里只列名，Phase 2 才填实现）：
# async def test_happy_path_full_10_nodes(client): ...
# async def test_return_path_node_5_back_to_node_3(client): ...
# async def test_reject_path_manager_review_terminates_flow(client): ...
# async def test_aggregation_node_results_in_applicant_confirm(client): ...
