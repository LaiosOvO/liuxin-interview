"""LangGraph 节点函数。

约定（CONTEXT §3 文件组织）：每个文件一个节点，避免单文件膨胀。

Phase 2 Plan 02 新增：hr_initial / hr_final
"""

from .apply import APPLY_NODE_NAME, APPLY_NODE_TITLE, apply_node
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
from .manager_review import (
    MANAGER_REVIEW_NODE_NAME,
    MANAGER_REVIEW_NODE_TITLE,
    manager_review_node,
)

__all__ = [
    "APPLY_NODE_NAME",
    "APPLY_NODE_TITLE",
    "HR_FINAL_NODE_DESCRIPTION",
    "HR_FINAL_NODE_NAME",
    "HR_FINAL_NODE_TITLE",
    "HR_INITIAL_NODE_DESCRIPTION",
    "HR_INITIAL_NODE_NAME",
    "HR_INITIAL_NODE_TITLE",
    "MANAGER_REVIEW_NODE_NAME",
    "MANAGER_REVIEW_NODE_TITLE",
    "apply_node",
    "hr_final_node",
    "hr_initial_node",
    "manager_review_node",
]
