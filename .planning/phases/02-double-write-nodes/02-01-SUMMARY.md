---
phase: 02-double-write-nodes
plan: 01
status: complete
date: 2026-05-16
tests_added: 15
tests_passing: 50
---

# Phase 2 Plan 01 — 双写规范完整化 + recover_from_db.py（SUMMARY）

## 已交付

### Code
- `backend/src/offboarding_flow/state_store/enums.py`：`ActionStatus.PENDING` 新增（双写中间态）
- `backend/src/offboarding_flow/state_store/repositories.py`：
  - `FlowRepository.append_node_result(flow_id, result)` — JSONB 数组应用层追加（SELECT FOR UPDATE 防并发）
  - `ActionRepository.mark_failed(action_id, error_message)`
  - `ActionRepository.mark_success(action_id)`
  - `ActionRepository.list_failed(limit, flow_id)`
- `backend/src/offboarding_flow/state_store/session.py`：`new_session()` 上下文管理器
- `backend/src/offboarding_flow/services/node_service.py`：双写规范完整版
  - action_log 创建用 PENDING
  - append_node_result 写业务层冗余
  - graph 失败 → 新 session mark_failed + raise HTTPException(500)
  - graph 成功 + 到 END → mark flow completed
- `backend/src/offboarding_flow/api/deps.py`：注入 `new_session` 工厂给 NodeService
- `backend/scripts/__init__.py` + `backend/scripts/recover_from_db.py`：CLI

### Tests
- `test_state_store.py`：+5 新签名/枚举测试（19 total）
- `test_node_service_double_write.py`：5 个集成测试（advance success / graph failure / append node_results / invalid action / reject）
- `test_recover_from_db.py`：5 个 CLI 单测（dry-run / 成功 / 失败重试 / flow_id 过滤 / --help）

### Docs
- `CHANGELOG.md`：`[Unreleased] / Added (Phase 2)` 段含 Plan 01 条目

## 关键决策

1. **session 失败补偿**：失败时通过 `session_factory` 注入新 session（避免污染原会话），生产用 `new_session()`；测试用 monkey-patch ActionRepository 走 fake store
2. **append_node_result 策略**：采用应用层读改写 + SELECT FOR UPDATE（PG 9.5+），易读且并发量低，不引入复杂 JSONB 拼装 SQL
3. **flow.status=completed**：移除 Phase 1 硬编码"manager_review advance → completed"，改为通过 `graph.aget_state(config).next` 判空检测 END
4. **recover_from_db retry**：in-memory 计数（不引入 retry_count 列迁移），单轮扫描每条只 invoke 1 次；多次跑脚本可继续累加

## 测试结果

```
50 passed, 3 deselected in 12.84s
```

零回归：Phase 1 既有 35 测试全部通过。

## 关键风险/已知问题

- **session_factory 在生产路径** `new_session()` 用全局 sessionmaker — 若 sessionmaker 尚未 init 会报错。Lifespan 启动顺序已保证此时 sessionmaker 已就绪
- **append_node_result FOR UPDATE** 会持有行锁直到事务 commit — Phase 2 流程并发低不会成为瓶颈；Phase 6 高并发场景需评估
- **recover_from_db 是手工运维工具** — Phase 6 接入定时扫描或告警可后置触发

## Next

Plan 02 / 03 / 04（节点函数 + 路由）可并行开始。
