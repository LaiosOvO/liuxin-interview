"""LangGraph 节点函数。

约定（CONTEXT §3 文件组织）：每个文件一个节点，避免单文件膨胀。

Phase 2 Plan 02 新增：hr_initial / hr_final
Phase 2 Plan 03 新增：device_return / access_revoke / knowledge_handover / finance_settle / legal_sign + _human_node_factory
Phase 2 Plan 04 新增：applicant_final_confirm（DF-02 ★★★★★）+ archive
Phase 4.5 新增：auto_archive_to_storage（PRD §18 加分项 — AutoNode 演示）
"""

from .access_revoke import (
    ACCESS_REVOKE_NODE_DESCRIPTION,
    ACCESS_REVOKE_NODE_NAME,
    ACCESS_REVOKE_NODE_TITLE,
    access_revoke_node,
)
from .applicant_final_confirm import (
    APPLICANT_FINAL_CONFIRM_NODE_DESCRIPTION,
    APPLICANT_FINAL_CONFIRM_NODE_NAME,
    APPLICANT_FINAL_CONFIRM_NODE_TITLE,
    applicant_final_confirm_node,
)
from .apply import APPLY_NODE_NAME, APPLY_NODE_TITLE, apply_node
from .archive import (
    ARCHIVE_NODE_DESCRIPTION,
    ARCHIVE_NODE_NAME,
    ARCHIVE_NODE_TITLE,
    archive_node,
)
from .auto_archive_to_storage import (
    AUTO_ARCHIVE_TO_STORAGE_NODE_DESCRIPTION,
    AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
    AUTO_ARCHIVE_TO_STORAGE_NODE_TITLE,
    auto_archive_to_storage_node,
)
from .device_return import (
    DEVICE_RETURN_NODE_DESCRIPTION,
    DEVICE_RETURN_NODE_NAME,
    DEVICE_RETURN_NODE_TITLE,
    device_return_node,
)
from .finance_settle import (
    FINANCE_SETTLE_NODE_DESCRIPTION,
    FINANCE_SETTLE_NODE_NAME,
    FINANCE_SETTLE_NODE_TITLE,
    finance_settle_node,
)
from .hr_final import (
    HR_FINAL_NODE_DESCRIPTION,
    HR_FINAL_NODE_NAME,
    HR_FINAL_NODE_TITLE,
    hr_final_node,
)
from .hr_initial import (
    HR_INITIAL_NODE_DESCRIPTION,
    HR_INITIAL_NODE_NAME,
    HR_INITIAL_NODE_TITLE,
    hr_initial_node,
)
from .knowledge_handover import (
    KNOWLEDGE_HANDOVER_NODE_DESCRIPTION,
    KNOWLEDGE_HANDOVER_NODE_NAME,
    KNOWLEDGE_HANDOVER_NODE_TITLE,
    knowledge_handover_node,
)
from .legal_sign import (
    LEGAL_SIGN_NODE_DESCRIPTION,
    LEGAL_SIGN_NODE_NAME,
    LEGAL_SIGN_NODE_TITLE,
    legal_sign_node,
)
from .manager_review import (
    MANAGER_REVIEW_NODE_NAME,
    MANAGER_REVIEW_NODE_TITLE,
    manager_review_node,
)

# 5 并行节点元数据（供 graph.py 总装 fan-out 时迭代用）
# tuple: (node_name, node_title, node_description, node_function)
PARALLEL_NODES_META: list[tuple[str, str, str, object]] = [
    (
        DEVICE_RETURN_NODE_NAME,
        DEVICE_RETURN_NODE_TITLE,
        DEVICE_RETURN_NODE_DESCRIPTION,
        device_return_node,
    ),
    (
        ACCESS_REVOKE_NODE_NAME,
        ACCESS_REVOKE_NODE_TITLE,
        ACCESS_REVOKE_NODE_DESCRIPTION,
        access_revoke_node,
    ),
    (
        KNOWLEDGE_HANDOVER_NODE_NAME,
        KNOWLEDGE_HANDOVER_NODE_TITLE,
        KNOWLEDGE_HANDOVER_NODE_DESCRIPTION,
        knowledge_handover_node,
    ),
    (
        FINANCE_SETTLE_NODE_NAME,
        FINANCE_SETTLE_NODE_TITLE,
        FINANCE_SETTLE_NODE_DESCRIPTION,
        finance_settle_node,
    ),
    (
        LEGAL_SIGN_NODE_NAME,
        LEGAL_SIGN_NODE_TITLE,
        LEGAL_SIGN_NODE_DESCRIPTION,
        legal_sign_node,
    ),
]

__all__ = [
    "ACCESS_REVOKE_NODE_DESCRIPTION",
    "ACCESS_REVOKE_NODE_NAME",
    "ACCESS_REVOKE_NODE_TITLE",
    "APPLICANT_FINAL_CONFIRM_NODE_DESCRIPTION",
    "APPLICANT_FINAL_CONFIRM_NODE_NAME",
    "APPLICANT_FINAL_CONFIRM_NODE_TITLE",
    "APPLY_NODE_NAME",
    "APPLY_NODE_TITLE",
    "ARCHIVE_NODE_DESCRIPTION",
    "ARCHIVE_NODE_NAME",
    "ARCHIVE_NODE_TITLE",
    "AUTO_ARCHIVE_TO_STORAGE_NODE_DESCRIPTION",
    "AUTO_ARCHIVE_TO_STORAGE_NODE_NAME",
    "AUTO_ARCHIVE_TO_STORAGE_NODE_TITLE",
    "DEVICE_RETURN_NODE_DESCRIPTION",
    "DEVICE_RETURN_NODE_NAME",
    "DEVICE_RETURN_NODE_TITLE",
    "FINANCE_SETTLE_NODE_DESCRIPTION",
    "FINANCE_SETTLE_NODE_NAME",
    "FINANCE_SETTLE_NODE_TITLE",
    "HR_FINAL_NODE_DESCRIPTION",
    "HR_FINAL_NODE_NAME",
    "HR_FINAL_NODE_TITLE",
    "HR_INITIAL_NODE_DESCRIPTION",
    "HR_INITIAL_NODE_NAME",
    "HR_INITIAL_NODE_TITLE",
    "KNOWLEDGE_HANDOVER_NODE_DESCRIPTION",
    "KNOWLEDGE_HANDOVER_NODE_NAME",
    "KNOWLEDGE_HANDOVER_NODE_TITLE",
    "LEGAL_SIGN_NODE_DESCRIPTION",
    "LEGAL_SIGN_NODE_NAME",
    "LEGAL_SIGN_NODE_TITLE",
    "MANAGER_REVIEW_NODE_NAME",
    "MANAGER_REVIEW_NODE_TITLE",
    "PARALLEL_NODES_META",
    "access_revoke_node",
    "applicant_final_confirm_node",
    "apply_node",
    "archive_node",
    "auto_archive_to_storage_node",
    "device_return_node",
    "finance_settle_node",
    "hr_final_node",
    "hr_initial_node",
    "knowledge_handover_node",
    "legal_sign_node",
    "manager_review_node",
]
