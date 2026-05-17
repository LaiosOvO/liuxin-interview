"""IM 抽象层（Phase 8A — ABS-01..02）。

本模块把"IM 平台监听 + 命令分发"做平台无关化抽象，让 Mattermost / Huly / Lark
等具体实现都遵守同一份 Protocol，并复用同一个 `dispatch_message` 通用函数。

子模块：
- `protocol`  — IMListener Protocol + DispatchFn 类型别名（ABS-01 / ABS-04）
- `dispatcher` — 通用 dispatch_message 函数（ABS-02）
- `context`   — IMHelpers dataclass（命令 handler 用以回写消息的回调集合）

不在本模块内的内容：
- 具体 listener 实现保留在 `workers/`（mattermost_listener.py / huly_listener.py）
- 具体业务命令仍在 `services/bot_service.py`
"""
