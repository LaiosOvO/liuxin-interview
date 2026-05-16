"""test_routes.py — 路由函数纯函数单测（Phase 2 Plan 02）。"""

from __future__ import annotations

from langgraph.graph import END

from offboarding_flow.flow_engine.routes import (
    APPLICANT_FINAL_CONFIRM,
    APPLY,
    ARCHIVE,
    DEVICE_RETURN,
    HR_FINAL,
    HR_INITIAL,
    PARALLEL_NODES,
    route_after_applicant,
    route_after_hr_final,
    route_after_hr_initial,
    route_after_manager_review,
)


def _state(action: str | None) -> dict:
    return {
        "flow_id": "x",
        "employee_id": "zhang.san",
        "current_action": action,
        "node_results": [],
        "context": {},
    }


class TestManagerReview:
    def test_reject_to_end(self):
        assert route_after_manager_review(_state("reject")) == END

    def test_advance_to_hr_initial(self):
        assert route_after_manager_review(_state("advance")) == HR_INITIAL

    def test_return_to_hr_initial(self):
        # manager_review 无上游可退，return 退化为推进
        assert route_after_manager_review(_state("return")) == HR_INITIAL

    def test_none_action_to_hr_initial(self):
        assert route_after_manager_review(_state(None)) == HR_INITIAL


class TestHrInitial:
    def test_reject_to_end(self):
        assert route_after_hr_initial(_state("reject")) == END

    def test_return_to_apply(self):
        assert route_after_hr_initial(_state("return")) == APPLY

    def test_advance_to_device_return(self):
        # 路由函数返回单节点；实际 fan-out 由 graph.py 用 Send 实现
        assert route_after_hr_initial(_state("advance")) == DEVICE_RETURN


class TestHrFinal:
    def test_reject_to_end(self):
        assert route_after_hr_final(_state("reject")) == END

    def test_return_to_device_return(self):
        # v1 简化：return 退回到第一个并行节点
        assert route_after_hr_final(_state("return")) == DEVICE_RETURN

    def test_advance_to_applicant(self):
        assert route_after_hr_final(_state("advance")) == APPLICANT_FINAL_CONFIRM


class TestApplicant:
    def test_return_to_hr_final(self):
        assert route_after_applicant(_state("return")) == HR_FINAL

    def test_advance_to_archive(self):
        assert route_after_applicant(_state("advance")) == ARCHIVE

    def test_reject_falls_back_to_advance(self):
        # 申请人节点无 reject — 防御性回退到 advance 路径（archive）
        assert route_after_applicant(_state("reject")) == ARCHIVE

    def test_none_action_to_archive(self):
        assert route_after_applicant(_state(None)) == ARCHIVE


def test_parallel_nodes_count_is_5():
    assert len(PARALLEL_NODES) == 5


def test_parallel_nodes_unique():
    assert len(set(PARALLEL_NODES)) == 5


def test_parallel_nodes_first_is_device_return():
    # graph.py 用 PARALLEL_NODES[0] 做 hr_final return 目标
    assert PARALLEL_NODES[0] == DEVICE_RETURN
