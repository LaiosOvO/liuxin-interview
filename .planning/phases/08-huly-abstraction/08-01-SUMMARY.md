---
phase: 08-huly-abstraction
plan: 01
subsystem: api
tags: [protocol, dispatcher, registry, outline, lark, mattermost, im-abstraction, doc-provider]

# Dependency graph
requires:
  - phase: 07-collab-doc-abstraction
    provides: DocProvider/IMProvider Protocol 基础（base.py 已含 create/update/list/ensure/get 5 方法）
  - phase: 04-notification-bot
    provides: BotService 11 命令 + MattermostListener WebSocket 长连接 + bot_command_parser
provides:
  - IMListener Protocol + IMHelpers + dispatch_message 通用分发函数（ABS-01/02）
  - DocProvider 完整 CRUD 生命周期（delete_document / list_documents_in_collection / delete_collection — ABS-03）
  - IMProvider register_command_listener 反向订阅 hook（ABS-04）
  - BotHandlerRegistry 动态查表分发（ABS-05）
  - CollectionInfo + DispatchFn 跨平台类型
affects:
  - 08-02 (ABS-06 节点元数据外提)
  - 08-03 (HulyDocProvider 实现 — 直接复用 ABS-03 3 个新方法)
  - 08-04 (HulyListener / HulyIMProvider 实现 — 直接复用 IMListener Protocol)
  - 08-05 (Huly bot 复用 dispatch_message + IMHelpers 模式)
  - 08-07 (MCP server 复用 BotHandlerRegistry 思路暴露 tools)

# Tech tracking
tech-stack:
  added:
    - typing.Protocol + runtime_checkable（IMListener / IMProvider / DocProvider 全用 Protocol 而非 ABC）
    - dataclasses.frozen=True（IMHelpers / CollectionInfo 不可变）
  patterns:
    - "Reverse subscription hook 模式（listener.register_command_listener → 注入 dispatch）"
    - "Dispatcher 模式（业务编排 ≠ 平台编解码，dispatch_message 函数 IM 无关）"
    - "HandlerRegistry 模式（command → handler 动态查表，0 if/elif）"
    - "Idempotent delete（404 视为幂等成功，避免重复操作冲突）"

key-files:
  created:
    - backend/src/offboarding_flow/im/__init__.py
    - backend/src/offboarding_flow/im/protocol.py
    - backend/src/offboarding_flow/im/context.py
    - backend/src/offboarding_flow/im/dispatcher.py
    - backend/src/offboarding_flow/services/bot_handler_registry.py
    - backend/tests/unit/im/test_protocol.py
    - backend/tests/unit/im/test_dispatcher.py
    - backend/tests/unit/providers/test_doc_provider_protocol.py
    - backend/tests/unit/providers/test_im_provider_protocol.py
    - backend/tests/unit/providers/test_outline_provider_lifecycle.py
    - backend/tests/unit/providers/test_outline_client_lifecycle.py
    - backend/tests/unit/providers/test_lark_provider_lifecycle.py
    - backend/tests/unit/services/test_bot_handler_registry.py
    - backend/tests/unit/services/test_bot_service_dispatch_via_registry.py
    - backend/tests/integration/test_mattermost_listener_dispatch.py
  modified:
    - backend/src/offboarding_flow/providers/base.py (ABS-03/04 — 加 3 doc 方法 + IM hook)
    - backend/src/offboarding_flow/providers/outline_provider.py (实现 3 个新方法)
    - backend/src/offboarding_flow/providers/lark_provider.py (LarkDocs 3 方法 + LarkIM register hook)
    - backend/src/offboarding_flow/providers/mattermost_provider.py (register_command_listener no-op)
    - backend/src/offboarding_flow/providers/wecom_provider.py (stub 同步补齐)
    - backend/src/offboarding_flow/providers/dingtalk_provider.py (stub 同步补齐)
    - backend/src/offboarding_flow/outline/client.py (加 delete_document / list_documents_in_collection / delete_collection)
    - backend/src/offboarding_flow/workers/mattermost_listener.py (实现 IMListener Protocol)
    - backend/src/offboarding_flow/main.py (lifespan 调 register_command_listener)
    - backend/src/offboarding_flow/services/bot_service.py (dispatch → HandlerRegistry 查表)

key-decisions:
  - "BotInvocationContext 暂不加 im_helpers 字段，保留 mm_helpers: dict 兼容 — Plan 02 ABS-05 后续重构再迁移（避免冲击 11 个 handler）"
  - "DispatchFn 在 im.protocol 和 providers.base 都定义一份（同结构 alias），避免 providers/ 模块依赖 im/ 模块"
  - "BotHandlerRegistry 用显式 _register_handlers() 而非全局 decorator — 简单 + 与实例 lifetime 对齐"
  - "delete_collection / delete_document 收到 not_found / 404 时视为幂等成功（不抛），便于重试安全"
  - "wecom / dingtalk stub provider 同步补齐新方法，避免 Protocol 不兼容破坏 mypy"

patterns-established:
  - "Reverse subscription hook: listener.register_command_listener(dispatch) — 让 listener 不知道业务命令"
  - "Dispatcher 函数模式: dispatch_message(*, sender, channel, message, im_helpers, settings, session_factory) — IM 平台无关"
  - "HandlerRegistry 模式: BotHandlerRegistry.register(cmd_name, handler) → invoke(cmd, ctx) — dispatch 0 if/elif"
  - "Provider Protocol 完整生命周期: create / update / get / list / delete / list_in_collection / delete_collection"

requirements-completed:
  - ABS-01
  - ABS-02
  - ABS-03
  - ABS-04
  - ABS-05

# Metrics
duration: 65min
completed: 2026-05-17
---

# Phase 8 Plan 01: IM 抽象层 + DocProvider/IMProvider 完善 + HandlerRegistry Summary

**IM 通道完全抽象（IMListener Protocol + 通用 dispatch_message + IMHelpers 注入）+ DocProvider 补齐 delete 闭环 + bot_service.dispatch 重构为 HandlerRegistry 动态查表 — 为 Phase 8 Huly 接入打好抽象基座，业务代码 0 修改即可切换 IM 平台**

## Performance

- **Duration:** ~65 min（含 5 个 atomic commit + 综合测试）
- **Started:** 2026-05-17T06:32:00Z (前一次 executor 已完成 task 01-01/02/03)
- **Resumed:** 2026-05-17T07:13:20Z (本次 executor 继续 01-04..01-08)
- **Completed:** 2026-05-17T08:18:00Z
- **Tasks:** 8 (3 + 5)
- **Files modified:** 18 (含 9 新建 + 9 修改)
- **Tests added:** 58（35 providers + 23 services + 复用前 task 19 IM 测试 = 总计 77 个新覆盖）

## Accomplishments

- **ABS-01/02 IM 抽象层基座** — IMListener Protocol + IMHelpers + dispatch_message 已就位（task 01-01/02/03，commits b27eb2d / 6db4968 / 9064c3a）
- **ABS-03 DocProvider 完整 CRUD** — Protocol + OutlineProvider + LarkDocsProvider + OutlineClient 底层 3 个新方法全实现，404/not_found 视为幂等成功
- **ABS-04 IMProvider listener hook** — Protocol 加 register_command_listener；Mattermost / Lark provider 实现 no-op；stub provider 同步补齐
- **ABS-05 HandlerRegistry 重构** — BotService.dispatch 内 11 if/elif → registry.invoke 一行；11 命令仍正常 dispatch 0 回归
- **测试覆盖** — 新代码 100% 行覆盖（im/ + bot_handler_registry + providers/base）；总 436 tests 收集，pre-existing 19 failures 不在 plan 范围

## Task Commits

每个 task 一个 atomic commit：

1. **Task 01-01: IMListener Protocol + IMHelpers** - `b27eb2d` (feat) — 前一次 executor
2. **Task 01-02: dispatch_message + 8 单测** - `6db4968` (feat) — 前一次 executor
3. **Task 01-03: MattermostListener 实现 Protocol + main.py 注册** - `9064c3a` (refactor) — 前一次 executor
4. **Task 01-04+05: DocProvider 3 生命周期方法 + IMProvider register hook (ABS-03/04)** - `3d4abd0` (feat) — 本次 executor
5. **Task 01-06: bot_service.dispatch 重构为 HandlerRegistry (ABS-05)** - `c358edc` (refactor) — 本次 executor

**Plan metadata commit:** (即将创建 — 含 SUMMARY.md + STATE.md + CHANGELOG.md + ROADMAP.md)

## Files Created/Modified

### IM 抽象层（task 01-01/02/03）
- `backend/src/offboarding_flow/im/__init__.py` - 模块入口
- `backend/src/offboarding_flow/im/protocol.py` - IMListener Protocol + DispatchFn 类型
- `backend/src/offboarding_flow/im/context.py` - IMHelpers frozen dataclass
- `backend/src/offboarding_flow/im/dispatcher.py` - dispatch_message 通用分发函数
- `backend/src/offboarding_flow/workers/mattermost_listener.py` - 实现 IMListener Protocol
- `backend/src/offboarding_flow/main.py` - lifespan 注册 dispatch_message

### Provider 完善（task 01-04/05 — ABS-03/04）
- `backend/src/offboarding_flow/providers/base.py` - 加 3 doc 方法 + IM register hook + CollectionInfo + DispatchFn
- `backend/src/offboarding_flow/providers/__init__.py` - 导出新类型
- `backend/src/offboarding_flow/providers/outline_provider.py` - 实现 3 个新方法
- `backend/src/offboarding_flow/providers/lark_provider.py` - LarkDocs 3 方法 + LarkIM register hook
- `backend/src/offboarding_flow/providers/mattermost_provider.py` - register_command_listener no-op
- `backend/src/offboarding_flow/providers/wecom_provider.py` - stub 同步补齐
- `backend/src/offboarding_flow/providers/dingtalk_provider.py` - stub 同步补齐
- `backend/src/offboarding_flow/outline/client.py` - delete_document / list_documents_in_collection / delete_collection

### Handler 重构（task 01-06 — ABS-05）
- `backend/src/offboarding_flow/services/bot_handler_registry.py` - BotHandlerRegistry + UnknownBotCommandError
- `backend/src/offboarding_flow/services/bot_service.py` - dispatch 改为 registry 查表 + 11 个 _dispatch_xxx wrapper

### 测试（覆盖全部 task）
- `backend/tests/unit/im/test_protocol.py` - 5 tests
- `backend/tests/unit/im/test_dispatcher.py` - 8 tests
- `backend/tests/integration/test_mattermost_listener_dispatch.py` - 6 tests
- `backend/tests/unit/providers/test_doc_provider_protocol.py` - 6 tests
- `backend/tests/unit/providers/test_im_provider_protocol.py` - 7 tests
- `backend/tests/unit/providers/test_outline_provider_lifecycle.py` - 6 tests
- `backend/tests/unit/providers/test_outline_client_lifecycle.py` - 8 tests
- `backend/tests/unit/providers/test_lark_provider_lifecycle.py` - 8 tests
- `backend/tests/unit/services/test_bot_handler_registry.py` - 10 tests
- `backend/tests/unit/services/test_bot_service_dispatch_via_registry.py` - 13 tests

### 文档
- `.planning/phases/08-huly-abstraction/08-01-SUMMARY.md` - 本文件
- `.planning/phases/08-huly-abstraction/deferred-items.md` - 19 个 pre-existing failures 标记
- `CHANGELOG.md` - Phase 8 Plan 01 段（[Unreleased] 内）

## Decisions Made

1. **BotInvocationContext 不在本 plan 加 im_helpers 字段** — 保留 `mm_helpers: dict` 与 Phase 7 兼容；Plan 02 ABS-06 重构时再统一迁移（避免冲击 11 个 handler 实现）
2. **DispatchFn 在两处定义** — `im.protocol.DispatchFn` 和 `providers.base.DispatchFn` 同结构 alias；为了让 providers/ 模块**不依赖** im/ 模块（保持单向依赖）
3. **BotHandlerRegistry 用显式 register** — 而非 `@bot_command("help")` 全局 decorator；理由：BotService 实例化时才有 self / session / flow_service 上下文，decorator 需要复杂的类级注册 + 实例 binding，工程复杂度 > 收益
4. **delete 操作 404 视为幂等成功** — Outline / Lark delete_document / delete_collection 收到 not_found / 404 时不抛，便于重试安全；其他 HTTP 错误 (5xx / 403) 正常抛 ProviderError
5. **wecom / dingtalk stub 必须补齐新方法** — 因为 Protocol runtime_checkable 严格检查；不补齐 mypy 报错 + 切换 provider 时崩

## Deviations from Plan

### Rule 2 - Missing Critical (合并 Task 01-04 + 01-05)

**1. IMProvider 加 register_command_listener 同时要补齐所有 IMProvider 实现**
- **Found during:** Task 01-04 commit 时 mypy 报错（MattermostProvider / LarkIMProvider 缺 register_command_listener）
- **Issue:** ABS-03 加 DocProvider 3 方法 + ABS-04 加 IMProvider register hook 本是两 task；但 IMProvider Protocol 加方法后所有 IMProvider 实现都必须补齐，否则 mypy / runtime_checkable 检查失败
- **Fix:** 把 task 01-04 和 01-05 合并到一个 commit (3d4abd0) — 因为它们逻辑上必须原子
- **Files modified:** providers/base.py + 所有 provider 实现
- **Verification:** mypy 0 error + IMProvider Protocol runtime_checkable 测试通过

### Rule 3 - Blocking

**2. ruff RUF043 — pytest.raises match 字符串需用 raw string**
- **Found during:** Task 01-04 第一次 pre-commit hook
- **Issue:** `pytest.raises(OutlineError, match="documents.delete")` 含未转义 `.` 元字符
- **Fix:** 改为 `r"documents\.delete"`
- **Files modified:** tests/unit/providers/test_outline_client_lifecycle.py
- **Verification:** ruff 0 error

---

**Total deviations:** 2 auto-fixed（1 architectural merge + 1 lint fix）
**Impact on plan:** 合并 01-04/05 让 commit boundary 更清晰（Protocol 加方法 + 所有实现补齐 = 单一原子变更）；lint fix 是机械修正不影响逻辑。

## Issues Encountered

- **19 个 pre-existing 测试失败** — 不是本 plan 引入（用 `git stash` 验证过）；包括 auth/test_role_router.py 6 个、test_api_flows.py 7 个、test_bot_command_parser.py 1 个、test_bot_service.py 1 个、notifications/test_email_envelope.py 1 个。已记录到 `.planning/phases/08-huly-abstraction/deferred-items.md` 留给后续单独 PR 修。
- **Pre-commit ruff-format 多次重写测试文件** — 已在每次 hook 反馈后重新 stage + commit，最终 commit 内容无格式异议。

## User Setup Required

无 — Plan 01 仅做内部抽象重构，0 外部服务配置变更。
（Phase 8 Huly 接入要 docker pull 14 个镜像 + service token 配置，那部分在 Plan 03/04 处理。）

## Next Phase Readiness

- ✅ Plan 02 (ABS-06 节点元数据外提) — 可独立开始，零依赖
- ✅ Plan 03 (HulyDocProvider 实现) — **可直接复用** ABS-03 3 个新方法（delete_document/list_documents_in_collection/delete_collection），按 Protocol 实现即可
- ✅ Plan 04 (HulyListener 实现) — **可直接复用** IMListener Protocol + IMHelpers + dispatch_message，按 Mattermost 模板做一份 Huly 版即可
- ✅ Plan 05 (Huly bot 命令) — **可直接复用** BotHandlerRegistry 模式
- ✅ Plan 07 (MCP server) — **可直接复用** HandlerRegistry 思路把 11 命令暴露成 MCP tools

**关键契约可复用于下游 plan：**
- `IMListener` Protocol — name / start / stop / register_command_listener
- `dispatch_message(*, sender_username, user_id, channel_id, channel_type, message, im_helpers, settings, session_factory)`
- `IMHelpers(post_channel, send_dm, ensure_in_channel=None)` — frozen dataclass
- `DocProvider` Protocol — 完整 8 方法（含 3 新增 lifecycle）
- `IMProvider` Protocol — 6 方法（含 register_command_listener hook）
- `BotHandlerRegistry.register(cmd_name, handler) → invoke(cmd, ctx)` — 0 if/elif

## Self-Check

执行 self-check 验证 SUMMARY 中声称的 artifact 全部存在：
- ✅ 5 个 commit hash (b27eb2d / 6db4968 / 9064c3a / 3d4abd0 / c358edc) 全部存在
- ✅ 9 个新建文件全部存在（im/* + bot_handler_registry + 5 个 test 文件 + deferred-items.md）
- ✅ 10 个修改文件 (providers/* + outline/client.py + workers/mattermost_listener.py + main.py + bot_service.py + base.py) 全部有 diff
- ✅ 100% 覆盖率验证（im/ + bot_handler_registry + providers/base = 163 stmts, 0 miss）
- ✅ 436 测试收集（baseline 378 + 本 plan 58 新）
- ✅ 19 个 pre-existing failures 已用 git stash 验证为基线问题

---
*Phase: 08-huly-abstraction*
*Plan: 01*
*Completed: 2026-05-17*
