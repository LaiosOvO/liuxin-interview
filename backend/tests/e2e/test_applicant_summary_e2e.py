"""test_applicant_summary_e2e.py — Slice 4C E2E 占位（默认 SKIP）。

实际 e2e 流程在 Slice 4D / Phase 4 完整 E2E 里覆盖（zhang.san 起流程 → 10 节点
→ 申请人确认 → 看到 glm_summary 在 interrupt payload 里）。

启用方式:
    OFFBOARDING_E2E_BASE_URL=http://localhost:8000 uv run pytest tests/e2e/test_applicant_summary_e2e.py -m e2e
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        "OFFBOARDING_E2E_BASE_URL" not in os.environ,
        reason="未设置 OFFBOARDING_E2E_BASE_URL — Slice 4D 集成 E2E 时启用",
    ),
]


async def test_applicant_confirm_payload_contains_glm_summary_field() -> None:
    """端到端：申请人确认节点 interrupt payload 含 glm_summary 字段。

    占位：Slice 4D 起一个完整流程跑到 applicant_final_confirm，
    断言 interrupt payload['glm_summary'] 字段存在（可为 None 表示降级）。
    """
    pytest.skip("Slice 4D 集成 E2E 时填充 — 当前仅占位")
