# Phase 08 Deferred Items（不在 Plan 01 范围）

> 这些是 Plan 01 (IM/Doc 抽象 + HandlerRegistry) 执行过程中发现的**预先存在**测试失败 / 待办，
> 不属于本 Plan 范围；不修。后续 Plan / 单独修 PR 处理。

## 预先存在测试失败（baseline，未被 Plan 01 改动引入）

### 1. tests/auth/test_role_router.py — 6 failures

测试期望旧的 hard-coded `/{role}` 路径，但 Phase 7 时已切换到基于 flow 的动态路由
`/flow/{flow_id}/node/{node_id}/`。测试本身需要更新以匹配新行为。

- `test_resolve_redirect_for_known_roles[applicant-/applicant]`
- `test_resolve_redirect_for_known_roles[manager-/manager]`
- `test_resolve_redirect_for_known_roles[hr-/hr]`
- `test_resolve_redirect_for_known_roles[it_admin-/it]`
- `test_resolve_redirect_for_known_roles[finance-/finance]`
- `test_resolve_redirect_for_known_roles[legal-/legal]`
- `test_resolve_redirect_unknown_role_fallback_to_applicant`
- `test_resolve_redirect_starts_with_slash_flow`

### 2. tests/test_api_flows.py — 7 failures

`AttributeError` — 测试 fixture / API contract 已变（Phase 7 envelope 重构）。

- `test_create_flow_returns_manager_review_waiting`
- `test_get_flow_returns_business_state`
- `test_list_flow_nodes_returns_apply_and_manager_review`
- `test_advance_action_completes_manager_review_node`
- `test_reject_action_marks_node_rejected`
- `test_duplicate_advance_returns_409`
- `test_invalid_action_value_returns_422`
- `test_envelope_shape_on_create_flow`

### 3. tests/test_bot_command_parser.py — 1 failure

`test_all_commands_constant_complete` 期望旧 8 命令，但 Phase 7 已加 3 个
（meeting-ingest / meeting-list / users-sync）。测试需更新。

### 4. tests/test_bot_service.py — 1 failure

`test_start_rejects_non_hr_user` 期望员工 `zhang.san` 给自己 start 时被拒，
但 BotService 的逻辑允许 self-apply（`is_self_apply=True` 旁路权限校验）。
这是产品决策不一致 — 测试或代码需要对齐。

### 5. tests/notifications/test_email_envelope.py — 1 failure

`test_envelope_demo_mode_routes_via_inbox_map` — 环境配置相关，预先失败。

### 6. tests/test_bot_command_parser.py::test_all_commands_constant_complete — 1 failure

旧测试断言只含 8 命令；Phase 7 加 meeting-* / users-sync 3 命令后未更新断言。

---

**Total baseline failures: 19**
- 已被 stash 验证为预先存在
- Plan 01 / 02 / 03 不修，留给后续单独 PR

---

## Plan 01 内自查

- 跑 `tests/unit/im/` + `tests/unit/providers/` + `tests/integration/test_mattermost_listener_dispatch.py` 全 PASS
- 跑 `git stash && pytest ... && git stash pop` 验证我新加的代码 0 引入新失败
- 全量 360 PASS + 27 skipped + 19 pre-existing failures（基线）
