"""Phase 4 Slice 4D — 后台 workers（事件驱动，非轮询）。

模块约定（用户明确要求）：
- **事件驱动**：用 PostgreSQL LISTEN/NOTIFY 触发器在 outbox INSERT 时实时唤醒 worker
- **心跳兜底**：60s 慢心跳处理偶发 NOTIFY 丢失（连接断开 / 重启窗口），不是主驱动
- **同进程**：worker 与 FastAPI 同进程跑（asyncio task）— v1 单 worker 足够
- **优雅停止**：FastAPI lifespan shutdown 时 cancel + await join

子模块：
- `outbox_drain`: pg_notify('outbox_new') → 拉 pending → 调 email_sender / mattermost_sender → mark success/failed
- `evidence_missing_detector`: 纯函数 helper，AI 报告与 simulate-evidence-missing 命令使用
"""

from __future__ import annotations

from .evidence_missing_detector import (
    EVIDENCE_MIN_LENGTH,
    detect_evidence_missing,
    is_text_evidence_missing,
)
from .outbox_drain import OutboxDrainWorker, drain_once

__all__ = [
    "EVIDENCE_MIN_LENGTH",
    "OutboxDrainWorker",
    "detect_evidence_missing",
    "drain_once",
    "is_text_evidence_missing",
]
