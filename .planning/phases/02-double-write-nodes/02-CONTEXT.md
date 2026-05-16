# Phase 2: 业务表双写规范完整化 + 节点函数完整化 + 申请人最终确认 — Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** `--auto`（基于 PRD v0.4 / SUMMARY.md / PITFALLS / ROADMAP §Phase 2 直接抽取；研究置信度 HIGH，不再 deep-dive）

---

<domain>
## Phase Boundary

**交付目标**：把 Phase 1 跑通的"最小双节点"骨架扩展为：
1. **双写规范完整版**：业务事务 commit → graph.ainvoke 的契约硬化（含失败补偿：mark `action_logs.status='failed'` + 告警 + `scripts/recover_from_db.py` 重试路径）。
2. **10 节点全部实现**：在 Phase 1 已有 `apply` + `manager_review` 基础上新增 8 节点：`hr_initial` / `device_return` / `access_revoke` / `knowledge_handover` / `finance_settle` / `legal_sign` / `hr_final` / `applicant_final_confirm` / `archive`。
3. **并行 fan-out + fan-in**：HR 初审 advance → 5 个并行节点 → 全部完成 → hr_final（LangGraph 自动 join）。
4. **申请人最终确认节点（DF-02 ★★★★★）**：聚合 `context.node_results[]` 渲染时间线 + 两态决策（确认 / 退回 hr_final）。
5. **退回路径**：HR 初审 return → apply；申请人确认 return → hr_final。
6. **拒绝路径**：manager_review reject、hr_initial reject、hr_final reject → 流程终止。
7. **scripts/recover_from_db.py 工具**：扫 `action_logs.status='failed'` → 重 invoke LangGraph。
8. **完整 E2E 测试**：zhang.san 起流程 → 走完 10 节点 → 申请人确认 → archive；异常路径（graph.invoke 故意抛错 → recover）。

**Phase 2 必须交付：**
1. `services/node_service.py` 双写规范增强：`mark_action_log_failed()` + alert 钩子 + 重试入口
2. `flow_engine/nodes/` 新增 8 个节点（共 10 个）
3. `flow_engine/graph.py` 扩展拓扑：10 节点 + 并行 fan-out/fan-in + 条件边（advance / return / reject 路由）
4. `flow_engine/state.py` 已就绪（NodeResult + Annotated reducer），可能需补充 context 字段
5. `state_store/repositories.py` 增强：`append_node_result()` 写 flow_instances.context.node_results[]
6. `scripts/recover_from_db.py` 工具
7. 三层测试覆盖：
   - **unit**: 每个节点函数幂等性测试 (`test_nodes_idempotent.py`)
   - **integration**: 双写一致性 + 失败补偿 + recover 工具 (`test_double_write.py` / `test_recover.py`)
   - **E2E**: `test_full_10_nodes_flow.py` 走完全部 10 节点 + 异常路径
8. CHANGELOG `[Unreleased]` 段追加 Phase 2 各 plan 完成记录

**Phase 2 不交付**（明确推到对应 phase）：
- 鉴权 / JWT 一键登录（Phase 3）
- 通知 / 邮件 / Mattermost Bot 入口 / 真实 outbox 发送（Phase 4 — 节点函数本 Phase 内只写 `notification_outbox` placeholder 或干脆不写，待 Phase 4 接入）
- AI 报告 / GLM 摘要（Phase 4）
- 自动节点（Phase 4.5）
- 前端 / nginx / 部署完善（Phase 5/6）

**Phase 2 验收**（ROADMAP §Phase 2 Success Criteria）：
1. 跑到任意节点故意让 `graph.ainvoke` 抛异常 → `action_logs.status='failed'` 可见 → `scripts/recover_from_db.py` 可手动重试
2. 申请人最终确认节点的汇总邮件占位文本（实际邮件 Phase 4）显示完整 10 节点时间线（含 actor / completed_at / result_text）
3. 退回路径正确：HR 初审 return → 回到 apply；申请人确认 return → 回到 hr_final
4. 拒绝路径正确：manager_review / hr_initial / hr_final reject → 流程终止（`flow_instances.status='rejected'`）
5. 5 个并行节点全部完成才进入 hr_final（fan-in 正确）

</domain>

<decisions>
## Implementation Decisions

### 1. 节点函数模板（PRD §4.2 + CONTEXT 01 §4 + PITFALLS #16）

所有人工节点统一用同一个模板，**幂等性靠 service 层 + node_repo.upsert 共同保障**：

```python
async def {node_name}_node(state: OffboardingState) -> dict:
    """
    幂等性：interrupt 抛 GraphInterrupt 后整个节点函数会重跑。
    业务表的 upsert 在 service 层（create_flow 或 submit_action 推进时）预先完成；
    节点函数本身只负责 LangGraph state 推进，不直接读写 DB（CONTEXT 01 §4 决策）。
    """
    decision = interrupt({
        "node_name": "{node_name}",
        "node_title": "{显示标题}",
        "node_description": "{操作说明}",
        "flow_id": state.get("flow_id"),
        "employee_id": state.get("employee_id"),
    })
    # decision 是 dict: {action, result_text, actor, completed_at?}
    if not isinstance(decision, dict):
        decision = {"action": "advance", "result_text": str(decision), "actor": "unknown"}
    return {
        "current_action": decision["action"],
        "node_results": [{
            "node_name": "{node_name}",
            "node_title": "{显示标题}",
            "result_text": decision.get("result_text", ""),
            "actor": decision.get("actor", "unknown"),
            "completed_at": decision.get("completed_at", datetime.now(UTC).isoformat()),
        }],
    }
```

### 2. 自动节点模板（apply / archive / applicant_final_confirm 内部聚合段）

**自动节点**：不调用 `interrupt()`，直接返回 state 推进到下一节点。

```python
async def archive_node(state: OffboardingState) -> dict:
    return {
        "current_action": "advance",
        "node_results": [{
            "node_name": "archive",
            "node_title": "归档",
            "result_text": "流程已归档",
            "actor": "system:archivist",
            "completed_at": datetime.now(UTC).isoformat(),
        }],
    }
```

### 3. 申请人最终确认节点（DF-02 ★★★★★）

`applicant_final_confirm` 是混合节点：
1. **进入时**：聚合 `state["node_results"]` 渲染时间线（Phase 2 只准备 timeline list，Phase 4 才发邮件）
2. **interrupt 等申请人决策**：仅 advance / return（无 reject）
3. **返回时**：current_action = advance → archive；current_action = return → hr_final

```python
async def applicant_final_confirm_node(state: OffboardingState) -> dict:
    timeline = state.get("node_results", [])  # Annotated reducer 已按时间累积
    decision = interrupt({
        "node_name": "applicant_final_confirm",
        "node_title": "申请人最终确认",
        "node_description": "请确认以下执行记录无误后归档；如有异议可退回 HR 终审复核。",
        "timeline": timeline,  # Phase 4 邮件渲染会用到
        "flow_id": state.get("flow_id"),
        "employee_id": state.get("employee_id"),
    })
    if not isinstance(decision, dict):
        decision = {"action": "advance", "result_text": str(decision), "actor": "unknown"}
    return {
        "current_action": decision["action"],
        "node_results": [{
            "node_name": "applicant_final_confirm",
            "node_title": "申请人最终确认",
            "result_text": decision.get("result_text", "无异议，已确认"),
            "actor": decision.get("actor", state.get("employee_id", "unknown")),
            "completed_at": decision.get("completed_at", datetime.now(UTC).isoformat()),
        }],
    }
```

### 4. StateGraph 拓扑（10 节点 + 并行 + 条件边）

```python
START
  → apply (自动)
  → manager_review (人工) ──reject→ END
  → hr_initial (人工) ──return→ apply
                       ──reject→ END
  ├──→ device_return (人工, parallel)        ──┐
  ├──→ access_revoke (人工, parallel)        ──┤
  ├──→ knowledge_handover (人工, parallel)   ──┼─→ hr_final (人工)
  ├──→ finance_settle (人工, parallel)       ──┤      ──reject→ END
  └──→ legal_sign (人工, parallel)            ──┘      ──return→ 任一并行节点（v1 简化为：return → device_return）
  → applicant_final_confirm (人工) ──return→ hr_final
                                    ──advance→ archive
  → archive (自动)
  → END
```

**关键设计**：
- 并行 fan-out 用 `builder.add_edge(hr_initial, [device_return, access_revoke, ...])` 同步发出
- 并行 fan-in 用 `builder.add_edge([device_return, access_revoke, ...], hr_final)` 等待全部完成
- 退回路径用 `add_conditional_edges` + 路由函数判断 `state["current_action"]`
- `hr_final return` 在 v1 简化为退回到 `device_return`（第一个并行节点），v2 可让 HR 选退回到哪个

### 5. 双写规范完整化（PRD §5.3.1 + PITFALLS #2）

`services/node_service.py.submit_action` 升级：

```python
async def submit_action(...):
    # 1. 业务校验（同 Phase 1）
    # 2. 写 action_log (status=pending) + node_states (要更新) — 同一事务
    action_log = await self.action_repo.create(..., status=ActionStatus.PENDING)
    await self.node_repo.complete(...)
    # 3. flow_instances.context.node_results[] 追加（应用层冗余，不依赖 LangGraph state）
    await self.flow_repo.append_node_result(flow_id, {...})
    # 4. 业务事务 commit
    await self.session.commit()
    # 5. graph.ainvoke(Command(resume=...))
    try:
        await self.graph.ainvoke(Command(resume={...}), config=config)
        await self.action_repo.mark_success(action_log.id)  # 新 session 写
    except Exception as e:
        # 6. mark action_log.failed + 告警钩子（Phase 2 用 logger.error，Phase 6 接 alert）
        await self.action_repo.mark_failed(action_log.id, str(e))
        await self._emit_alert(flow_id, node_id, action, str(e))
        raise HTTPException(500, f"流程推进失败已记录，可通过 recover 脚本重试: {e}")
    # 7. 推进 graph 成功 → 计算 next_node 返回给前端
    return {...}
```

### 6. recover_from_db.py（PITFALLS #2 修复路径）

```
扫 action_logs WHERE status='failed' AND created_at > now() - interval '24 hours'
对每条 failed action_log:
  1. 拿出 flow_id, node_state_id, action, result_text, actor
  2. 校验 flow_instances 当前状态 + node_states 当前状态（业务侧应已 complete 了）
  3. 重 invoke: graph.ainvoke(Command(resume={action, result_text, actor}), config={"configurable":{"thread_id": flow_id}})
  4. 成功 → mark action_log.status='success'
  5. 失败 → 增加 retry_count，超过 3 次告警
```

CLI 接口：`uv run python -m scripts.recover_from_db [--flow-id=xxx] [--dry-run]`

### 7. 退回路径（FLOW-05）路由函数

```python
def _route_after_hr_initial(state) -> str:
    action = state.get("current_action")
    if action == "reject":
        return END  # 流程终止
    if action == "return":
        return "apply"  # 退回到 apply（重新填写）
    return "device_return"  # 推进到第一个并行节点（5 个并行 LangGraph 自动 fan-out）

def _route_after_hr_final(state) -> str:
    action = state.get("current_action")
    if action == "reject":
        return END
    if action == "return":
        return "device_return"  # v1 简化：退回到第一个并行节点（重跑 5 个并行）
    return "applicant_final_confirm"

def _route_after_applicant(state) -> str:
    action = state.get("current_action")
    if action == "return":
        return "hr_final"
    return "archive"
```

### 8. 并行 fan-out / fan-in 在 LangGraph 1.x 的写法

```python
# 5 并行节点同时 fan-out
PARALLEL_NODES = ["device_return", "access_revoke", "knowledge_handover", "finance_settle", "legal_sign"]
for parallel_node in PARALLEL_NODES:
    builder.add_node(parallel_node, parallel_node_factory(parallel_node))
    # hr_initial advance 后 fan-out 到所有并行节点
    builder.add_edge("hr_initial", parallel_node)  # LangGraph 自动并行调度
    # 并行节点全部 done 后 fan-in 到 hr_final
    builder.add_edge(parallel_node, "hr_final")
```

LangGraph 在 add_edge 多源时自动等待所有源节点完成才进入目标节点（join）。

### 9. flow_instances.context.node_results[] 应用层冗余

虽然 LangGraph state 也有 `node_results`（Annotated reducer），但**业务表里冗余一份**避免：
- 申请人确认时直接查业务表，不读 LangGraph checkpoint（双层状态分离硬约束）
- 演示 / 报表查询直接 SQL，不绕 LangGraph

`FlowRepository.append_node_result()`：
```python
async def append_node_result(self, flow_id: UUID, result: dict) -> None:
    """JSONB 数组追加（PG 9.5+ jsonb_set + array_append）。"""
    stmt = (
        update(FlowInstance)
        .where(FlowInstance.id == flow_id)
        .values(
            context=func.jsonb_set(
                FlowInstance.context,
                "{node_results}",
                func.coalesce(FlowInstance.context["node_results"], "[]::jsonb")
                + func.jsonb_build_array(result),
            )
        )
    )
    await self.session.execute(stmt)
```

或者更简单的 Python 侧 read-modify-write（行级锁 `SELECT ... FOR UPDATE`）。

### 10. 测试策略（CLAUDE.md §2 + §2.1）

**三层测试覆盖**：

**Unit**（不接 DB / graph）：
- `test_state_reducer.py`: node_results Annotated 累计正确
- `test_route_functions.py`: 三态决策路由函数返回正确的下一节点
- `test_node_results_aggregation.py`: 申请人节点 timeline 拼装正确

**Integration**（真 postgres，禁止 mock — CLAUDE.md §2.3）：
- `test_node_idempotency.py`: 同一节点 service.submit_action 调两次（模拟 graph 重跑）业务表无重复
- `test_double_write_failure.py`: 故意 patch graph.ainvoke 抛异常 → action_log.status=failed + flow 不卡死
- `test_recover_from_db.py`: 跑 recover 脚本能修复 failed action

**E2E**（真 postgres + real graph + InMemorySaver checkpoint）：
- `test_full_10_nodes_flow.py`: 走完整个流程（advance 全部）+ 校验所有 node_states.status=done + context.node_results.length=10 + flow.status=completed
- `test_e2e_reject_at_manager.py`: manager_review reject → flow.status=rejected + 后续节点不创建
- `test_e2e_return_at_hr_initial.py`: hr_initial return → 回到 apply
- `test_e2e_return_at_applicant.py`: applicant return → 回到 hr_final → advance → archive
- `test_e2e_parallel_fan_in.py`: 5 并行节点必须全部 done 才进入 hr_final

覆盖率 ≥ 80%。

### 11. CHANGELOG 每个 plan 完成后追加

每个 plan SUMMARY 写完后，向 `CHANGELOG.md` 的 `[Unreleased]` 段追加：

```
## [Unreleased]

### Added (Phase 2)
- 2026-05-16 — Phase 2 Plan 01：double-write 失败补偿 + recover_from_db.py 脚本
- 2026-05-16 — Phase 2 Plan 02：hr_initial + hr_final 两个串行节点 + 退回路径
...
```

### Claude's Discretion

下列细节由 plan 编排时自行决定：

- LangGraph 并行节点的具体 add_edge 调用方式（每个写一条 vs 批量）
- 申请人 timeline 渲染格式（dict list vs dataclass list）
- `_emit_alert` 钩子的 Phase 2 实现（推荐：logger.error 即可，Phase 6 接 alert）
- recover_from_db.py 是否做成 click CLI 还是 argparse（推荐 argparse 不引入新依赖）
- 路由函数是否抽公共工厂（推荐：每节点一个简短路由函数，prose-style 更易读）
- Plan 拆分粒度（推荐 5-6 个 plan，按 wave 并行）
- 节点函数命名空间（已沿用 `flow_engine.nodes.{node_name}.{node_name}_node`）
- E2E 测试是否用 webapp-testing skill — Phase 2 无 UI，**不用** browser harness，纯 pytest + httpx
- failed action_log 的 dead-letter / max retry 策略（Phase 2 不实现自动重试，仅手动 recover 脚本）

</decisions>

<specifics>
## Specific Ideas

- **测试数据**：用 polyfactory 生成 OffboardingState；员工默认 `zhang.san`；assignee 写死 `manager:li.si` / `hr:hr.alice` / `it:it.charlie` / `finance:fin.david` / `legal:legal.eve`
- **并行节点 fan-in**：LangGraph 自动 join — 不需要自己实现 barrier
- **演示场景**：起流程 → 8 次 API advance（每个节点的 submit_action）→ 申请人 advance → archive 自动 → flow.status=completed
- **异常场景**：在第 3 个 advance 时 mock graph.ainvoke 抛 ConnectionError → 校验 action_log.status='failed' + 节点状态仍是 done（业务侧已 commit）+ flow_instances.context.node_results 已追加 → 跑 recover → graph 重 invoke 成功 → action_log.status='success'

</specifics>

<deferred>
## Deferred Ideas

- 节点函数内直接读写 DB（CONTEXT 01 §4 决策：节点函数纯 state 推进，DB 操作在 service 层）
- 通知发送（Phase 4）
- LLM 摘要（Phase 4，applicant 节点本 Phase 只准备 timeline）
- 鉴权（Phase 3）
- AutoNode 类型（Phase 4.5）
- Dashboard "重发通知" 按钮（Phase 5）
- Mattermost callback（Phase 4）
- 自动 retry 策略（Phase 6 timeout_scan）

</deferred>

---

*Phase: 02-double-write-nodes*
*Context gathered: 2026-05-16 (auto mode from PRD v0.4 + ROADMAP §Phase 2 + Phase 1 实现 + PITFALLS)*
