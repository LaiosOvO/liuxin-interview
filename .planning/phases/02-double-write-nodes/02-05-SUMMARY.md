---
phase: 02-double-write-nodes
plan: 05
status: complete
date: 2026-05-16
tests_added: 9
tests_passing: 126
---

# Phase 2 Plan 05 — graph.py 10 节点完整拓扑总装（SUMMARY）

## 已交付

- `flow_engine/graph.py`：完整重写 `_build_state_graph`
  - 10 节点全部注册（apply / manager_review / hr_initial / 5 并行 / hr_final / applicant_final_confirm / archive）
  - 6 条直接边 + 4 条条件边
  - 用 `Send` 实现 hr_initial advance → 5 并行 fan-out
  - 5 并行节点 add_edge → hr_final 实现 fan-in
  - 退回 / 拒绝 / advance 路径全部接入 routes.py
- `test_graph_topology.py`：9 个拓扑结构 + 行为测试
- 调整 `test_api_flows`：`test_advance_action_completes_manager_review_node`（manager_review advance 后 flow 不再 completed）

## 关键技术点

- **LangGraph 1.x dynamic fan-out**：`add_conditional_edges(node, route_fn, mapping)` 中 route_fn 可返回 `list[Send]`，触发并行调度
- **fan-in 自动**：多个源节点用 `add_edge(name, target)` 时 LangGraph 默认 wait-all
- **add_conditional_edges mapping**：用 list 形式（不是 dict）声明所有可能目标节点
- **hr_final return 简化**：v1 退回到第一个并行节点（PARALLEL_NODES[0] = device_return）— v2 可让 HR 选退回到哪个

## 测试结果

126 passed（Phase 1 35 + Plan 01-04 82 + Plan 05 9）。

## 已修复的 Phase 1 测试回归

- `test_advance_action_completes_manager_review_and_flow` → 改名 `test_advance_action_completes_manager_review_node`，断言改为 `flow_status == "in_progress"`（Phase 2 拓扑下 manager_review 不再是末节点）
