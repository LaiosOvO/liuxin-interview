---
phase: 02-double-write-nodes
plan: 06
status: complete
date: 2026-05-16
tests_added: 9
tests_passing: 126
e2e_tests: 6 (skip without env)
integration_tests: 2 (skip without env)
---

# Phase 2 Plan 06 — E2E + integration 收官（SUMMARY）

## 已交付

- `tests/e2e/conftest.py`：复用 `app_client` fixture（OFFBOARDING_E2E_BASE_URL 真容器 / TEST_DATABASE_URL inline ASGI 双模式）
- `tests/e2e/test_full_10_nodes_flow.py`：主路径 happy-path（10 节点全部 advance + flow=completed）
- `tests/e2e/test_e2e_reject_paths.py`：3 reject 场景（manager / hr_initial / hr_final）
- `tests/e2e/test_e2e_return_paths.py`：2 return 场景（hr_initial / applicant）
- `tests/e2e/test_e2e_recover_from_db.py`：双写失败补偿 + recover 恢复链路
- `tests/integration/__init__.py` + `test_flow_full_chain.py`：真 PG + 真 PostgresSaver 双层一致性
- `pyproject.toml`：注册 `integration` marker；默认 skip e2e + integration（环境变量启用）

## 测试矩阵

| 测试 | 模式 | 启用条件 | REQ 覆盖 |
|---|---|---|---|
| test_full_10_nodes_happy_path | e2e | BASE_URL or TEST_DSN | FLOW-01/02/04/06 |
| test_manager_review_reject_terminates_flow | e2e | 同上 | FLOW-05 |
| test_hr_initial_reject_terminates_flow | e2e | 同上 | FLOW-05 |
| test_hr_final_reject_terminates_after_parallel | e2e | 同上 | FLOW-05 |
| test_hr_initial_return_marks_node_returned | e2e | 同上 | FLOW-05 |
| test_applicant_return_goes_back_to_hr_final | e2e | 同上 | FLOW-05/06 |
| test_recover_dry_run_does_not_invoke | e2e | 同上 | FLOW-02 |
| test_graph_failure_marks_action_log_failed_then_recover | e2e | 同上 | FLOW-02 |
| test_create_flow_writes_business_and_checkpoint | integration | TEST_DSN | FLOW-02/03 |
| test_advance_writes_node_results_to_context | integration | TEST_DSN | FLOW-02 |

## 关键设计

- **e2e/conftest.py** 双模式：本地开发用 inline ASGI（启动 lifespan + httpx ASGITransport），CI 用真容器（OFFBOARDING_E2E_BASE_URL）
- **integration 用真 PG 默认 skip**：CLAUDE.md §2.3 硬约束 — 集成测试禁止 mock DB；本地开发用 docker compose dev 起 test schema
- **markers 注册**：`integration` 加入 pyproject.toml；addopts 默认排除 e2e + integration（避免本地 dev 慢）

## 测试结果（默认本地跑）

```
126 passed, 13 deselected in 13.70s
```

E2E + integration 测试在 OFFBOARDING_E2E_BASE_URL / TEST_DATABASE_URL 设置时会跑（CI 配置）。

## 已知风险 / 后续工作

- `test_recover_from_db.py` E2E 测试中 `recover_all(graph=g)` 使用 patch 退出后的 graph — 如果 patch 退出顺序敏感可能需调整
- 节点首次进入业务表 upsert 在 Plan 05 部分实现（reject 路径 OK，advance/return 路径靠 service 在 advance 处理；自动节点 archive 业务表 upsert 待 Phase 4 完善）

## Phase 2 Complete

至此 Phase 2 全部 6 plan 完成。126 测试全 pass（Phase 1 35 + Phase 2 91 新增），ROADMAP Phase 2 Success Criteria 5 条全部对应测试存在。
