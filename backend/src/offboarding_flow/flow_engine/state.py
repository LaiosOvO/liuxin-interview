"""OffboardingState TypedDict（CONTEXT §5 + PRD §8）。

关键约定（PITFALLS #4）：
- node_results 必须用 Annotated[list, operator.add] reducer
- 否则并行 fan-out（Phase 2）时 last-write-wins 静默丢数据
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class NodeResult(TypedDict):
    """单个节点的执行结果（累计到 OffboardingState.node_results）。"""

    node_name: str
    node_title: str
    result_text: str
    actor: str
    completed_at: str  # ISO 8601


class OffboardingState(TypedDict):
    """LangGraph 的状态结构 — 与业务表是两层独立状态（CONTEXT §3.3）。

    字段：
    - flow_id: 流程实例 UUID（字符串形式，与业务表 flow_instances.id 对应）
    - employee_id: 离职员工 username
    - current_action: 最近一次决策（advance / return / reject）
    - node_results: 累计所有节点的执行结果（必须 Annotated reducer 防 PITFALLS #4）
    - context: 流程级上下文（员工信息、模板配置等）
    """

    flow_id: str
    employee_id: str
    current_action: str | None
    node_results: Annotated[list[NodeResult], add]
    context: dict
