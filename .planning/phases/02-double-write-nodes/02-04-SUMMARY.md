---
phase: 02-double-write-nodes
plan: 04
status: complete
date: 2026-05-16
tests_added: 24
tests_passing: 117
---

# Phase 2 Plan 04 — applicant_final_confirm + archive + timeline_renderer（SUMMARY）

## 已交付

- `flow_engine/nodes/applicant_final_confirm.py` — DF-02 ★★★★★
  - interrupt payload 含 `timeline` 字段（state.node_results 整段，前端 + Phase 4 邮件渲染都用）
  - 仅 advance / return 两态决策；reject 防御性回退到 advance（PRD §4.5.2）
  - 默认 actor = state.employee_id（申请人本人）
  - 默认 result_text：advance → "无异议，已确认"；return → "有异议，退回 HR 终审"
- `flow_engine/nodes/archive.py`：自动节点（无 interrupt），actor=system:archivist
- `services/timeline_renderer.py`：纯函数 render_timeline(node_results, header?, include_separator?) — 多行文本输出（PRD §4.5.2 示例格式）
- `services/__init__.py`：暴露 render_timeline
- `flow_engine/nodes/__init__.py`：扩展 export 6 个新名称

## 测试

- `test_timeline_renderer.py`：14 测试（4 _format_completed_at 边界 + 10 render_timeline 主路径）
- `test_applicant_final_confirm.py`：7 测试（advance / return / reject 回退 / 默认 actor / 默认 result_text × 2 / ISO 时区）
- `test_archive_node.py`：3 测试（返回结构 / ISO / async 函数）

## 关键设计

- timeline_renderer 是纯函数 — 后续 Phase 4 邮件模板可直接复用，无任何 DB / graph 依赖
- applicant 节点设计了"reject sanitize" 防御性回退 — 即使前端误传 reject 也走 advance（PRD §4.5.2 申请人节点无 reject）

## 测试结果

117 passed（Phase 1 35 + Plan 01-03 58 + Plan 04 24）。零回归。
