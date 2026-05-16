"""LangGraph 节点函数。

约定（CONTEXT §3 文件组织）：每个文件一个节点，避免单文件膨胀。
"""

from .apply import APPLY_NODE_NAME, APPLY_NODE_TITLE, apply_node
from .manager_review import (
    MANAGER_REVIEW_NODE_NAME,
    MANAGER_REVIEW_NODE_TITLE,
    manager_review_node,
)

__all__ = [
    "APPLY_NODE_NAME",
    "APPLY_NODE_TITLE",
    "MANAGER_REVIEW_NODE_NAME",
    "MANAGER_REVIEW_NODE_TITLE",
    "apply_node",
    "manager_review_node",
]
