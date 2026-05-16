"""Bot 命令解析器（BOT-02 — PRD §16.2 + §16.5）。

严格白名单 + 正则解析；不接受 eval / 任意输入（PRD §16.5 安全约束）。

支持 8 命令：
- start <username>
- status <flow_id>
- report <flow_id>
- suggest <flow_id>
- list [active|completed|stuck]
- help
- simulate-timeout <flow_id> <node_name>
- simulate-evidence-missing <flow_id> <node_name>

输入示例（Outgoing Webhook 的 text 字段）：
- "@offboarding-bot start zhang.san"
- "@offboarding-bot list stuck"
- "start zhang.san"  （bot mention 已被 Mattermost 剥掉）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# 命令字面量（避免散落字符串）
CMD_START: Final = "start"
CMD_STATUS: Final = "status"
CMD_REPORT: Final = "report"
CMD_SUGGEST: Final = "suggest"
CMD_LIST: Final = "list"
CMD_HELP: Final = "help"
CMD_SIMULATE_TIMEOUT: Final = "simulate-timeout"
CMD_SIMULATE_EVIDENCE_MISSING: Final = "simulate-evidence-missing"

# 会议纪要 ↔ Outline 协作文档（新增）
CMD_MEETING_INGEST: Final = "meeting-ingest"
CMD_MEETING_LIST: Final = "meeting-list"
CMD_USERS_SYNC: Final = "users-sync"

ALL_COMMANDS: Final[tuple[str, ...]] = (
    CMD_START,
    CMD_STATUS,
    CMD_REPORT,
    CMD_SUGGEST,
    CMD_LIST,
    CMD_HELP,
    CMD_SIMULATE_TIMEOUT,
    CMD_SIMULATE_EVIDENCE_MISSING,
    CMD_MEETING_INGEST,
    CMD_MEETING_LIST,
    CMD_USERS_SYNC,
)

LIST_FILTERS: Final[tuple[str, ...]] = ("active", "completed", "stuck")
DEFAULT_LIST_FILTER: Final = "active"

# 严格正则（PRD §16.5）：
# - username: 字母 / 数字 / . / _ / -（公司域账户惯例）
# - flow_id / node_id: UUID 全式 36 位 (或 8 位短 ID — PRD §16.4 样例用 8 位)
# - node_name: 字母 + 下划线（与 flow_engine.nodes 命名约束一致）

_USERNAME_RE: Final = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")
_FLOW_ID_RE: Final = re.compile(
    r"^[0-9a-f]{8}$"  # 8 位短 ID
    r"|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"  # full UUID
)
_NODE_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# bot mention 前缀（Outgoing Webhook 可能保留也可能剥掉）
_MENTION_PREFIX_RE: Final = re.compile(r"^@\S+\s+")

# 自然语言"申请离职"快捷指令 — 由调用方（webhook）用 user_name 当 employee_id 起流程
SELF_APPLY_SENTINEL: Final = "__SELF__"
_SELF_APPLY_PHRASES: Final = (
    "我要离职",
    "我要走了",
    "申请离职",
    "离职申请",
    "提离职",
    "想离职",
)


class BotCommandParseError(Exception):
    """命令解析失败 — 调用方应回复用户 "未知命令，输入 help 查看帮助"。"""


@dataclass(frozen=True)
class BotCommand:
    """解析后的命令 DTO（immutability）。"""

    name: str  # 命令名（ALL_COMMANDS 之一）
    args: tuple[str, ...]  # 位置参数（已 strip / 已校验）
    raw: str  # 原始输入文本（便于审计）


def parse_command(text: str) -> BotCommand:
    """解析一条 Mattermost 文本输入为 BotCommand。

    Args:
        text: 原始用户输入（可能含 "@offboarding-bot " 前缀）

    Returns:
        BotCommand

    Raises:
        BotCommandParseError: 命令不认识 / 参数缺失 / 参数格式不合法
    """
    if not text or not text.strip():
        raise BotCommandParseError("命令为空")

    raw = text.strip()
    # 剥 @offboarding-bot 前缀（如有）
    stripped = _MENTION_PREFIX_RE.sub("", raw, count=1).strip()
    if not stripped:
        raise BotCommandParseError("命令为空（仅有 mention）")

    # 自然语言"我要离职"等 → start SELF（webhook 层把 SELF 替换成 user_name）
    if any(phrase in stripped for phrase in _SELF_APPLY_PHRASES):
        return BotCommand(name=CMD_START, args=(SELF_APPLY_SENTINEL,), raw=raw)

    # tokenize（按空白分隔；保留连字符 — simulate-timeout 是单 token）
    tokens = stripped.split()
    cmd_name = tokens[0].lower()

    if cmd_name not in ALL_COMMANDS:
        raise BotCommandParseError(f"未知命令 '{cmd_name}'；输入 help 查看可用命令列表")

    args = tuple(tokens[1:])

    # 校验各命令的参数白名单 + 正则
    if cmd_name == CMD_HELP:
        if args:
            # help 不接受参数 — 严格白名单
            raise BotCommandParseError("help 命令不需要参数")
        return BotCommand(name=cmd_name, args=(), raw=raw)

    if cmd_name == CMD_START:
        if len(args) != 1:
            raise BotCommandParseError("用法：start <username>")
        if not _USERNAME_RE.match(args[0]):
            raise BotCommandParseError(
                f"用户名格式不合法：'{args[0]}'（必须字母开头，只能含字母 / 数字 / . _ -）"
            )
        return BotCommand(name=cmd_name, args=(args[0],), raw=raw)

    if cmd_name in (CMD_STATUS, CMD_REPORT, CMD_SUGGEST):
        if len(args) != 1:
            raise BotCommandParseError(f"用法：{cmd_name} <flow_id>")
        if not _FLOW_ID_RE.match(args[0]):
            raise BotCommandParseError(
                f"flow_id 格式不合法：'{args[0]}'（必须是 8 位短 ID 或完整 UUID）"
            )
        return BotCommand(name=cmd_name, args=(args[0],), raw=raw)

    if cmd_name == CMD_LIST:
        if len(args) == 0:
            return BotCommand(name=cmd_name, args=(DEFAULT_LIST_FILTER,), raw=raw)
        if len(args) != 1:
            raise BotCommandParseError(f"用法：list [{('|').join(LIST_FILTERS)}]")
        if args[0] not in LIST_FILTERS:
            raise BotCommandParseError(
                f"list 过滤值不合法：'{args[0]}'（允许：{', '.join(LIST_FILTERS)}）"
            )
        return BotCommand(name=cmd_name, args=(args[0],), raw=raw)

    if cmd_name in (CMD_SIMULATE_TIMEOUT, CMD_SIMULATE_EVIDENCE_MISSING):
        if len(args) != 2:
            raise BotCommandParseError(f"用法：{cmd_name} <flow_id> <node_name>")
        if not _FLOW_ID_RE.match(args[0]):
            raise BotCommandParseError(
                f"flow_id 格式不合法：'{args[0]}'（必须是 8 位短 ID 或完整 UUID）"
            )
        if not _NODE_NAME_RE.match(args[1]):
            raise BotCommandParseError(
                f"node_name 格式不合法：'{args[1]}'（小写字母 / 数字 / 下划线，字母开头）"
            )
        return BotCommand(name=cmd_name, args=(args[0], args[1]), raw=raw)

    if cmd_name == CMD_MEETING_INGEST:
        # meeting-ingest 接受**任意后续多行文本**作为会议纪要原文
        body = stripped[len(CMD_MEETING_INGEST) :].strip()
        if not body:
            raise BotCommandParseError("用法：meeting-ingest <粘贴会议纪要全文，支持多行>")
        if len(body) < 30:
            raise BotCommandParseError("会议纪要太短（< 30 字符）— 请粘贴完整内容")
        # 整段当作单参数（不再按空白拆分）
        return BotCommand(name=cmd_name, args=(body,), raw=raw)

    if cmd_name == CMD_MEETING_LIST:
        if args:
            raise BotCommandParseError("meeting-list 不需要参数")
        return BotCommand(name=cmd_name, args=(), raw=raw)

    if cmd_name == CMD_USERS_SYNC:
        if args:
            raise BotCommandParseError("users-sync 不需要参数")
        return BotCommand(name=cmd_name, args=(), raw=raw)

    # 不应到达 — ALL_COMMANDS 已穷举
    raise BotCommandParseError(f"内部错误：命令 '{cmd_name}' 未实现处理分支")
