# 后端 E2E 测试

## 范围

这里放**真后端容器**（docker compose 起来）的端到端测试，不用 mock。

- Phase 1（本目录）：`test_full_flow.py` 覆盖最小 2 节点 + docker restart 恢复
- Phase 2：扩展到 10 节点 + 并行 fan-out + 申请人最终确认
- Phase 4：邮件 / Mattermost / GLM 摘要降级 / 演示模式收件箱
- Phase 4.5：自动节点 + mock-archive-service
- Phase 5：浏览器 E2E（请见 `frontend/tests/e2e/`）
- Phase 6：超时扫描 + 整体演示 runbook

## 怎么跑

**手动冒烟**（推荐）：

```bash
# 1. 起容器（postgres + redis + flow-api）
bash scripts/dev_up.sh

# 2. 跑 shell 冒烟（curl-based，给人看的）
bash scripts/smoke_test.sh

# 3. 跑 pytest E2E（python httpx，更精确）
export OFFBOARDING_E2E_BASE_URL=http://localhost:8000
cd backend && uv run pytest tests/e2e/ -v -m e2e
```

**CI 不跑 E2E**：pytest 默认排除 `-m e2e`（pyproject.toml 已配 `addopts = "-m 'not e2e'"`）

## 演示模式场景清单（CLAUDE.md §2.1）

下列场景会在对应 phase 加用例：

| 场景 | Phase | 用例文件 |
|------|-------|---------|
| 起流程 → 10 节点全部 advance 走完 | 2 | test_full_flow.py::test_happy_path |
| result_text 校验 + node_results 聚合 | 2 | test_full_flow.py::test_aggregation |
| 申请人邮件聚合 + GLM 摘要 | 4 | test_full_flow.py::test_applicant_summary |
| 任意节点 return（回退到上游） | 2 | test_full_flow.py::test_return_path |
| 任意关键节点 reject（终止） | 2 | test_full_flow.py::test_reject_path |
| 超时模拟（timeout_scan 触发） | 6 | test_full_flow.py::test_timeout_simulate |
| 证据缺失检测 | 4 | test_full_flow.py::test_evidence_missing |
| GLM API down（降级） | 4 | test_full_flow.py::test_glm_degradation |
| QQ SMTP down（outbox 重试） | 4 | test_full_flow.py::test_smtp_outbox_retry |
| 进程崩溃 docker restart 恢复 | **1（本 phase）** | test_full_flow.py::test_docker_restart_recovers |

## 浏览器 E2E（browser-harness）

走 `webapp-testing` skill（Playwright 后端），spec 在 `frontend/tests/e2e/` — Phase 5 才落地。
本目录只放"curl-based 后端 E2E"。
