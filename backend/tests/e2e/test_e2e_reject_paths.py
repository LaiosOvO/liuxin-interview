"""test_e2e_reject_paths.py — 关键节点 reject 流程终止（FLOW-05）。

测试矩阵：
- manager_review reject → flow.status=rejected + 下游节点不进入业务表
- hr_initial reject → 同上
- hr_final reject（5 并行完成后）→ 同上
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e]


async def _list_waiting(client, flow_id):
    r = await client.get(f"/api/flows/{flow_id}/nodes")
    return [n for n in r.json()["data"] if n["status"] == "waiting_human"]


async def _advance(client, flow_id, node_id, result_text, actor):
    r = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "advance", "result_text": result_text, "actor": actor},
    )
    assert r.status_code == 200, f"advance failed: {r.text}"


async def _reject(client, flow_id, node_id, reason, actor):
    r = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "reject", "result_text": reason, "actor": actor},
    )
    assert r.status_code == 200, f"reject failed: {r.text}"


async def test_manager_review_reject_terminates_flow(app_client):
    r = await app_client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = r.json()["data"]["flow_id"]
    nodes = await _list_waiting(app_client, flow_id)
    manager = next(n for n in nodes if n["name"] == "manager_review")

    await _reject(app_client, flow_id, manager["id"], "不同意离职", "li.si")

    # flow=rejected
    r = await app_client.get(f"/api/flows/{flow_id}")
    assert r.json()["data"]["status"] == "rejected"

    # hr_initial 不出现
    nodes_after = (await app_client.get(f"/api/flows/{flow_id}/nodes")).json()["data"]
    assert "hr_initial" not in {n["name"] for n in nodes_after}


async def test_hr_initial_reject_terminates_flow(app_client):
    r = await app_client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = r.json()["data"]["flow_id"]
    nodes = await _list_waiting(app_client, flow_id)
    m = next(n for n in nodes if n["name"] == "manager_review")
    await _advance(app_client, flow_id, m["id"], "同意", "li.si")

    nodes = await _list_waiting(app_client, flow_id)
    h = next(n for n in nodes if n["name"] == "hr_initial")
    await _reject(app_client, flow_id, h["id"], "材料造假", "hr.alice")

    r = await app_client.get(f"/api/flows/{flow_id}")
    assert r.json()["data"]["status"] == "rejected"

    # 5 并行节点不出现
    nodes_after = (await app_client.get(f"/api/flows/{flow_id}/nodes")).json()["data"]
    parallel_names = {
        "device_return",
        "access_revoke",
        "knowledge_handover",
        "finance_settle",
        "legal_sign",
    }
    actual_names = {n["name"] for n in nodes_after}
    assert not (parallel_names & actual_names), f"reject 后并行节点不应出现: {actual_names}"


async def test_hr_final_reject_terminates_after_parallel(app_client):
    """走完 manager → hr_initial → 5 并行 → hr_final reject。"""
    r = await app_client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = r.json()["data"]["flow_id"]

    # 推进到 5 并行
    for name in ["manager_review", "hr_initial"]:
        nodes = await _list_waiting(app_client, flow_id)
        n = next(x for x in nodes if x["name"] == name)
        await _advance(app_client, flow_id, n["id"], "ok", "tester")

    # advance 5 并行
    nodes = await _list_waiting(app_client, flow_id)
    for n in nodes:
        await _advance(app_client, flow_id, n["id"], "done", "tester")

    # hr_final reject
    nodes = await _list_waiting(app_client, flow_id)
    hf = next(n for n in nodes if n["name"] == "hr_final")
    await _reject(app_client, flow_id, hf["id"], "材料矛盾", "hr.bob")

    r = await app_client.get(f"/api/flows/{flow_id}")
    assert r.json()["data"]["status"] == "rejected"

    # applicant / archive 不进入业务表
    nodes_after = (await app_client.get(f"/api/flows/{flow_id}/nodes")).json()["data"]
    after_names = {n["name"] for n in nodes_after}
    assert "applicant_final_confirm" not in after_names
    assert "archive" not in after_names
