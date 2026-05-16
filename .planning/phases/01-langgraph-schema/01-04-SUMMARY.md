---
phase: 01-langgraph-schema
plan: 04
subsystem: workflow-engine
tags: [langgraph, state-machine, interrupt, checkpoint, postgressaver, async]
requires:
  - phase: 01
    provides: [pyproject.toml 含 langgraph + langgraph-checkpoint-postgres + psycopg]
provides:
  - OffboardingState TypedDict（含 Annotated reducer）
  - AsyncPostgresSaver 工厂 + CLI --setup 入口
  - 2 个最小节点（apply 自动 + manager_review interrupt）
  - StateGraph 单例 + build_graph / get_graph / dispose_graph 接口
affects: [Plan 02 entrypoint.sh checkpointer --setup, Plan 05 lifespan build_graph, Plan 06 service 层 graph.ainvoke, Phase 2 扩展到 10 节点]

tech-stack:
  added:
    - langgraph (latest) StateGraph + AsyncPostgresSaver + InMemorySaver
    - psycopg 3.x + psycopg-pool AsyncConnectionPool
  patterns:
    - dynamic interrupt() + Command(resume=...) 而非 interrupt_before（SUMMARY R3）
    - Annotated[list, operator.add] reducer 防 PITFALLS #4
    - 全局单例 graph + 显式 build_graph(use_memory_saver=) 切换

key-files:
  created:
    - backend/src/offboarding_flow/flow_engine/__init__.py
    - backend/src/offboarding_flow/flow_engine/state.py
    - backend/src/offboarding_flow/flow_engine/checkpointer.py
    - backend/src/offboarding_flow/flow_engine/nodes/__init__.py
    - backend/src/offboarding_flow/flow_engine/nodes/apply.py
    - backend/src/offboarding_flow/flow_engine/nodes/manager_review.py
    - backend/src/offboarding_flow/flow_engine/graph.py
    - backend/tests/test_flow_engine.py

key-decisions:
  - "用 langgraph.checkpoint.postgres.aio.AsyncPostgresSaver（langgraph 内置）— 不是独立 package"
  - "checkpointer.py 用 AsyncConnectionPool min/max_size=2/10（演示环境足够）"
  - "psycopg 3 必须 autocommit=True/dict_row/prepare_threshold=0（PITFALLS #1 防 deadlock）"
  - "节点函数 Phase 1 不直接调 Repository — 业务表的 upsert 由 Plan 06 service 层提前做"
  - "manager_review_node interrupt 返回 dict 也需鲁棒兼容 str/非 dict（防 langgraph 不同版本行为）"

patterns-established:
  - "Pattern: dynamic interrupt — 节点函数内 decision = interrupt({...}); API 层 Command(resume=...)"
  - "Pattern: 节点函数幂等 — interrupt 重跑节点函数时业务表用 upsert 不出错（节点函数本身保持纯函数）"
  - "Pattern: CLI 入口（python -m ... --setup）— 提供 entrypoint.sh 调用点"

requirements-completed:
  - FLOW-01
  - FLOW-03
  - DEPLOY-05

duration: 10min
completed: 2026-05-16
---

# Phase 1 Plan 04: LangGraph 引擎骨架

**LangGraph StateGraph + AsyncPostgresSaver + 2 节点 + dynamic interrupt + checkpoint 恢复 — Phase 1 状态机引擎完整骨架。**

## Performance

- Duration: ~10 min
- Tasks: 3
- Files modified: 8

## Accomplishments

1. **OffboardingState TypedDict** — flow_id / employee_id / current_action / node_results（Annotated reducer 防 PITFALLS #4）/ context
2. **AsyncPostgresSaver 工厂** — psycopg 3 + AsyncConnectionPool + autocommit/dict_row/prepare_threshold=0 (PITFALLS #1)
3. **CLI 入口** — `python -m offboarding_flow.flow_engine.checkpointer --setup` 供 entrypoint.sh 调（DEPLOY-05）
4. **2 个最小节点** — apply（自动节点不 interrupt）+ manager_review（dynamic interrupt + Command resume 模式 SUMMARY R3）
5. **graph.py** — StateGraph START→apply→manager_review→END + build_graph(use_memory_saver=) 切换 + dispose_graph 单例清理
6. **测试** — 6 个用例全通过，含 InMemorySaver checkpoint 恢复测试（证明同 thread_id 不重跑 apply）+ Annotated reducer 静态校验

## Verification Results

- pytest tests/test_flow_engine.py 6/6 pass
- 关键测试：test_checkpoint_recovers_from_interrupt 证明 graph_v2 用同 saver 重建后 apply_count == 1（checkpoint 恢复有效）

## Next

Plan 06 把 graph 接入 API service 层，实现完整双写规范（业务事务 commit → graph.ainvoke）。
