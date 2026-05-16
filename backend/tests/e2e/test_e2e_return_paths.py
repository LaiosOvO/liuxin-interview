"""test_e2e_return_paths.py — 退回路径 E2E（FLOW-05）。

测试矩阵：
- hr_initial return → apply（重做申请）
- applicant return → hr_final（HR 复核） → 再 advance → archive
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
    assert r.status_code == 200, r.text


async def _return(client, flow_id, node_id, reason, actor):
    r = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "return", "result_text": reason, "actor": actor},
    )
    assert r.status_code == 200, r.text


async def test_hr_initial_return_marks_node_returned(app_client):
    """hr_initial return → 节点状态变 returned；流程仍 in_progress。"""
    r = await app_client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = r.json()["data"]["flow_id"]

    # advance manager_review
    nodes = await _list_waiting(app_client, flow_id)
    m = next(n for n in nodes if n["name"] == "manager_review")
    await _advance(app_client, flow_id, m["id"], "ok", "li.si")

    # return hr_initial
    nodes = await _list_waiting(app_client, flow_id)
    h = next(n for n in nodes if n["name"] == "hr_initial")
    await _return(app_client, flow_id, h["id"], "材料不全", "hr.alice")

    # hr_initial 应被 mark returned；流程未终止（仍 in_progress 或 graph 路由到 apply）
    nodes = (await app_client.get(f"/api/flows/{flow_id}/nodes")).json()["data"]
    hr_node = next(n for n in nodes if n["name"] == "hr_initial")
    # 视实现：业务侧 mark returned；graph 路由到 apply 后可能再次 upsert hr_initial 为 waiting_human
    assert hr_node["status"] in ("returned", "waiting_human"), hr_node["status"]
    # flow 未 rejected
    r = await app_client.get(f"/api/flows/{flow_id}")
    assert r.json()["data"]["status"] != "rejected"


async def test_applicant_return_goes_back_to_hr_final(app_client):
    """走到 applicant → return → hr_final 重新 waiting → advance → archive → completed。"""
    r = await app_client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = r.json()["data"]["flow_id"]

    # 推进到 applicant 节点
    for name in ["manager_review", "hr_initial"]:
        nodes = await _list_waiting(app_client, flow_id)
        n = next(x for x in nodes if x["name"] == name)
        await _advance(app_client, flow_id, n["id"], "ok", "tester")

    # 5 并行 advance
    nodes = await _list_waiting(app_client, flow_id)
    for n in nodes:
        await _advance(app_client, flow_id, n["id"], "done", "tester")

    # hr_final advance
    nodes = await _list_waiting(app_client, flow_id)
    hf = next(n for n in nodes if n["name"] == "hr_final")
    await _advance(app_client, flow_id, hf["id"], "通过", "hr.bob")

    # applicant return → 应回到 hr_final
    nodes = await _list_waiting(app_client, flow_id)
    ap = next(n for n in nodes if n["name"] == "applicant_final_confirm")
    await _return(app_client, flow_id, ap["id"], "有异议", "zhang.san")

    # hr_final 应再次 waiting_human
    nodes = await _list_waiting(app_client, flow_id)
    hf_again = [n for n in nodes if n["name"] == "hr_final"]
    assert (
        hf_again
    ), f"applicant return 后 hr_final 应再次 waiting，当前 waiting={[n['name'] for n in nodes]}"
    assert hf_again[0]["status"] == "waiting_human"

    # 再 advance hr_final → applicant 再 advance → archive
    await _advance(app_client, flow_id, hf_again[0]["id"], "复核通过", "hr.bob")
    nodes = await _list_waiting(app_client, flow_id)
    ap2 = next(n for n in nodes if n["name"] == "applicant_final_confirm")
    await _advance(app_client, flow_id, ap2["id"], "确认", "zhang.san")

    r = await app_client.get(f"/api/flows/{flow_id}")
    assert r.json()["data"]["status"] == "completed"
