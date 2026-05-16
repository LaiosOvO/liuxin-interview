"""LangGraph 引擎模块。

提供：
- OffboardingState TypedDict（CONTEXT §5）
- AsyncPostgresSaver 工厂 + CLI --setup 入口
- 节点函数（apply / manager_review）
- StateGraph 构建 + 全局单例
"""

from .checkpointer import (
    dispose_checkpointer,
    make_checkpointer,
    setup_checkpointer_schema,
)
from .graph import build_graph, dispose_graph, get_graph
from .state import NodeResult, OffboardingState

__all__ = [
    "NodeResult",
    "OffboardingState",
    "build_graph",
    "dispose_checkpointer",
    "dispose_graph",
    "get_graph",
    "make_checkpointer",
    "setup_checkpointer_schema",
]
