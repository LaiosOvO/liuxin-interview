"""test_full_10_nodes_flow.py — Phase 2 主路径 E2E（CLAUDE.md §2.1 全流程测试）。

走完 10 节点的完整 happy-path：
1. POST /api/flows → manager_review waiting
2-3. advance manager_review → advance hr_initial → 5 并行 waiting
4-8. 依次 advance 5 个并行 → hr_final waiting
9. advance hr_final → applicant_final_confirm waiting
10. advance applicant → archive 自动 → flow=completed

需要 OFFBOARDING_E2E_BASE_URL 或 TEST_DATABASE_URL（conftest 处理）。
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e]


async def _advance(client, flow_id, node_id, result_text, actor):
    r = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "advance", "result_text": result_text, "actor": actor},
    )
    assert r.status_code == 200, f"advance failed: {r.status_code} {r.text}"
    return r.json()["data"]


async def _get_waiting_nodes(client, flow_id):
    r = await client.get(f"/api/flows/{flow_id}/nodes")
    assert r.status_code == 200
    return [n for n in r.json()["data"] if n["status"] == "waiting_human"]


async def _get_waiting_node_by_name(client, flow_id, name):
    waiting = await _get_waiting_nodes(client, flow_id)
    match = [n for n in waiting if n["name"] == name]
    assert match, f"node {name} not waiting; current={[n['name'] for n in waiting]}"
    return match[0]


async def test_full_10_nodes_happy_path(app_client):
    """跑完全部 10 节点 happy path（ROADMAP §Phase 2 Success #2）。"""
    # Step 1: 起流程
    r = await app_client.post("/api/flows", json={"employee_id": "zhang.san"})
    assert r.status_code == 200, r.text
    flow_id = r.json()["data"]["flow_id"]

    # Step 2: manager_review advance
    node = await _get_waiting_node_by_name(app_client, flow_id, "manager_review")
    await _advance(app_client, flow_id, node["id"], "同意离职", "li.si")

    # Step 3: hr_initial advance — 推进后应出现 5 并行 waiting
    node = await _get_waiting_node_by_name(app_client, flow_id, "hr_initial")
    await _advance(app_client, flow_id, node["id"], "材料齐全", "hr.alice")

    # Step 4: 5 个并行节点全部 advance（顺序无关 — fan-in 自动 join）
    waiting = await _get_waiting_nodes(app_client, flow_id)
    parallel_names = {
        "device_return",
        "access_revoke",
        "knowledge_handover",
        "finance_settle",
        "legal_sign",
    }
    actual = {n["name"] for n in waiting}
    assert parallel_names.issubset(actual), f"应有 5 并行 waiting, 实际 {actual}"

    parallel_results = {
        "device_return": ("MacBook 已归还", "it.charlie"),
        "access_revoke": ("权限已回收", "it.charlie"),
        "knowledge_handover": ("文档已交接", "li.si"),
        "finance_settle": ("结算完成", "fin.david"),
        "legal_sign": ("协议已签", "legal.eve"),
    }
    for n in waiting:
        if n["name"] in parallel_results:
            text, actor = parallel_results[n["name"]]
            await _advance(app_client, flow_id, n["id"], text, actor)

    # Step 5: 5 并行全部 done → hr_final waiting
    node = await _get_waiting_node_by_name(app_client, flow_id, "hr_final")
    await _advance(app_client, flow_id, node["id"], "终审通过", "hr.bob")

    # Step 6: applicant_final_confirm advance
    node = await _get_waiting_node_by_name(app_client, flow_id, "applicant_final_confirm")
    await _advance(app_client, flow_id, node["id"], "无异议", "zhang.san")

    # Step 7: archive 自动 → flow=completed
    r = await app_client.get(f"/api/flows/{flow_id}")
    assert r.json()["data"]["status"] == "completed"

    # Step 8: 业务表 node_states 应含全部关键节点 done
    nodes = (await app_client.get(f"/api/flows/{flow_id}/nodes")).json()["data"]
    done_names = {n["name"] for n in nodes if n["status"] == "done"}
    expected_done = {
        "manager_review",
        "hr_initial",
        "device_return",
        "access_revoke",
        "knowledge_handover",
        "finance_settle",
        "legal_sign",
        "hr_final",
        "applicant_final_confirm",
    }
    # archive 节点（自动）也应 done — 取决于 node_service 是否对自动节点也 upsert
    missing = expected_done - done_names
    assert not missing, f"缺少 done 节点: {missing}; 实际 done = {done_names}"
