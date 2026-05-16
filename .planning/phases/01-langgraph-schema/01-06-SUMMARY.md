---
phase: 01-langgraph-schema
plan: 06
subsystem: api
tags: [fastapi, service-layer, double-write, depends, integration-test]
requires:
  - phase: 01
    provides: [pyproject.toml]
  - plan: 03
    provides: [Repository 层 + Session 工厂]
  - plan: 04
    provides: [graph 单例 + get_graph]
  - plan: 05
    provides: [FastAPI app + lifespan + envelope]
provides:
  - flow_service / node_service（双写规范最小版）
  - api/deps.py 完整 DI 容器
  - 4 个业务 API 端点（POST/GET/GET/POST）
  - 10 个集成测试（InMemorySaver + fake Repository）
affects: [Plan 07 E2E 真容器冒烟, Phase 2 完善双写失败补偿 + recover 脚本]

tech-stack:
  added:
    - asgi-lifespan（测试用）+ dependency_overrides（FastAPI 测试模式）
  patterns:
    - 双写规范：业务事务 commit → graph.ainvoke
    - service 层不主动 commit graph 失败（Phase 1 简化版）
    - app.dependency_overrides 替换真 Repository 用 fake 实现，全程不连真 DB

key-files:
  created:
    - backend/src/offboarding_flow/services/__init__.py
    - backend/src/offboarding_flow/services/flow_service.py
    - backend/src/offboarding_flow/services/node_service.py
    - backend/src/offboarding_flow/api/deps.py
    - backend/src/offboarding_flow/api/flows.py
    - backend/src/offboarding_flow/api/nodes.py
    - backend/tests/test_api_flows.py
  modified:
    - backend/src/offboarding_flow/api/__init__.py（暴露 flows_router + nodes_router）

key-decisions:
  - "Phase 1 简化版：service 在 advance 时直接 mark flow_instances.status=completed（manager_review 是末节点）"
  - "Phase 1 简化版：reject 直接 mark flow_instances.status=rejected"
  - "graph.ainvoke 失败仅 log 不抛错（业务表已 commit，前端 GET 仍能读对的状态）— Phase 2 加 mark action_log.failed + recover"
  - "节点函数预先在 create_flow 时 upsert（apply=done + manager_review=waiting_human）— 节点函数 interrupt 重跑时不重复（PITFALLS #16 + ON CONFLICT 已保护）"
  - "测试用 dependency_overrides 替换 Repository — 比修改 service 代码加 DI 更干净"

patterns-established:
  - "Pattern: service 层职责 — 编排 Repository + LangGraph，不直接做 SQL/HTTP"
  - "Pattern: Phase 1 双写规范 — 业务事务全部完成 commit → 才动 graph（失败容错），Phase 2 加补偿"

requirements-completed:
  - FLOW-01
  - FLOW-03

duration: 12min
completed: 2026-05-16
---

# Phase 1 Plan 06: API 业务集成（4 端点 + 双写规范最小版）

**4 个业务 API 端点上线 + service 层双写规范最小版 + 10 个集成测试全通过 — Phase 1 业务闭环就位。**

## Performance

- Duration: ~12 min
- Tasks: 3
- Files modified: 7

## Accomplishments

1. **services/flow_service.py** — create_flow 双写规范（INSERT flow + INSERT action_log + upsert apply 节点 done + upsert manager_review 节点 waiting_human → commit → graph.ainvoke 跑到 interrupt） + get_flow + list_nodes
2. **services/node_service.py** — submit_action 三态决策映射（advance→done/completed / return→returned / reject→rejected/rejected） + 409 状态校验 + 业务事务 commit → graph.ainvoke Command resume
3. **api/deps.py** — 6 个 Depends 工厂（get_db_session / get_flow_repo / get_node_repo / get_action_repo / get_flow_service / get_node_service）
4. **api/flows.py + api/nodes.py** — 4 个端点完整实现 + pydantic schema 校验
5. **api/__init__.py** 暴露 flows_router + nodes_router；main.py 自动注册
6. **测试** — 10 个集成测试全通过（InMemorySaver + fake Repository + dependency_overrides）

## Verification Results

- pytest tests/test_api_flows.py 10/10 pass
- 5 个 API 路径全部在 app.routes（/api/health + /api/flows × 4）
- 双层状态分离：GET /api/flows 只读业务表，不读 checkpoint
- 双写顺序：业务 commit → graph.ainvoke（PRD §5.3 Pattern 1）

## Next

Plan 07 E2E 骨架 + 手动冒烟脚本 + CHANGELOG 标 Phase 1 完成。
