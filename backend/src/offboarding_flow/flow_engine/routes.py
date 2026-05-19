"""路由函数集中模块（PRD §4.1 DAG + 02-CONTEXT §7）。

条件边路由统一规则：
- current_action == "reject" → 终止 (END)
- current_action == "return" → 退回到上游指定节点
- 其他（advance）→ 推进到下游节点

节点名常量在本模块集中定义，避免 graph.py / 路由函数互相 import 节点模块导致循环。
"""

from __future__ import annotations

import logging

from langgraph.graph import END

from offboarding_flow.flow_engine.state import OffboardingState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 节点名常量（与 nodes/__init__.py 中保持一致 — 后者从节点文件 re-export）
# ---------------------------------------------------------------------------
APPLY = "apply"
MANAGER_REVIEW = "manager_review"
HR_INITIAL = "hr_initial"
DEVICE_RETURN = "device_return"
ACCESS_REVOKE = "access_revoke"
KNOWLEDGE_HANDOVER = "knowledge_handover"
FINANCE_SETTLE = "finance_settle"
LEGAL_SIGN = "legal_sign"
HR_FINAL = "hr_final"
APPLICANT_FINAL_CONFIRM = "applicant_final_confirm"
AUTO_ARCHIVE_TO_STORAGE = "auto_archive_to_storage"  # Phase 4.5（PRD §18 加分项）
ARCHIVE = "archive"

# 5 并行节点（Plan 03 实现，Plan 05 总装）
PARALLEL_NODES: list[str] = [
    DEVICE_RETURN,
    ACCESS_REVOKE,
    KNOWLEDGE_HANDOVER,
    FINANCE_SETTLE,
    LEGAL_SIGN,
]


# ---------------------------------------------------------------------------
# 路由函数
# ---------------------------------------------------------------------------
def route_after_manager_review(state: OffboardingState) -> str:
    """manager_review 三态决策路由。

    - reject → END（流程终止）
    - return → apply（退回到申请人，让其修改申请理由后重新提交）
    - advance → hr_initial（推进 HR 初审）
    """
    action = state.get("current_action")
    logger.info("[route] after manager_review action=%s", action)
    if action == "reject":
        return END
    if action == "return":
        return APPLY
    return HR_INITIAL


def route_after_hr_initial(state: OffboardingState) -> str:
    """hr_initial 三态决策路由。

    - reject → END
    - return → apply（要求重新填写申请材料）
    - advance → device_return（路由函数返回单节点名占位；实际 fan-out 5 并行靠 graph.py
      add_conditional_edges 配合 _route_after_hr_initial_to_parallel 用 Send 实现）
    """
    action = state.get("current_action")
    logger.info("[route] after hr_initial action=%s", action)
    if action == "reject":
        return END
    if action == "return":
        return APPLY
    return DEVICE_RETURN


def route_after_hr_final(state: OffboardingState) -> str:
    """hr_final 三态决策路由。

    - reject → END
    - return → device_return（v1 简化：退回到第一个并行节点，重做 5 节点）
    - advance → applicant_final_confirm
    """
    action = state.get("current_action")
    logger.info("[route] after hr_final action=%s", action)
    if action == "reject":
        return END
    if action == "return":
        return DEVICE_RETURN
    return APPLICANT_FINAL_CONFIRM


def route_after_applicant(state: OffboardingState) -> str:
    """applicant_final_confirm 两态决策路由（无 reject — PRD §4.5.2）。

    Phase 4.5（PRD §18）：advance 不再直接到 archive，先到 auto_archive_to_storage
    （自动调外部归档服务），成功后才会自动跑到 archive 终结。

    - return → hr_final（HR 复核）
    - advance（及任何防御性回退）→ auto_archive_to_storage（自动节点）
    """
    action = state.get("current_action")
    logger.info("[route] after applicant_final_confirm action=%s", action)
    if action == "return":
        return HR_FINAL
    return AUTO_ARCHIVE_TO_STORAGE
