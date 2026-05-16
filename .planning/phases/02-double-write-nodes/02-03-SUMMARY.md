---
phase: 02-double-write-nodes
plan: 03
status: complete
date: 2026-05-16
tests_added: 20
tests_passing: 93
---

# Phase 2 Plan 03 — 5 并行节点 + _human_node_factory（SUMMARY）

## 已交付

- `flow_engine/nodes/_human_node_factory.py`：通用人工节点工厂（interrupt + decision + node_results 模板）
- 5 节点文件：device_return / access_revoke / knowledge_handover / finance_settle / legal_sign（每节点 < 20 行）
- `flow_engine/nodes/__init__.py`：扩展 export + `PARALLEL_NODES_META` 元数据
- `tests/test_nodes_parallel.py`：20 测试（参数化跑 5 节点 × 3 行为 + 5 元数据校验）

## 关键设计

- 5 节点函数完全相同的 interrupt + Command(resume) 行为 — 用 factory 复用避免重复
- 每节点文件只声明常量 + 调 `make_human_node()` —— 易扩展（v2 加节点只需复制 9 行模板）
- `PARALLEL_NODES_META` 暴露 `(name, title, description, fn)` 四元组供 graph.py 总装迭代

## 测试结果

93 passed（Phase 1 35 + Plan 01-02 38 + Plan 03 20）。零回归。
