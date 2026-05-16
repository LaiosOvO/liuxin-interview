"""bot_command_parser 单元测试（BOT-02 — PRD §16.2 + §16.5）。

覆盖：
- 8 命令白名单解析正确性
- 参数缺失 / 多余参数 → 报错
- username / flow_id / node_name 正则严格性
- @offboarding-bot mention 前缀剥离
- 边界 / 空输入 / unicode / 大小写
"""

from __future__ import annotations

import pytest

from offboarding_flow.services.bot_command_parser import (
    ALL_COMMANDS,
    BotCommandParseError,
    parse_command,
)


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------
def test_help_simple() -> None:
    cmd = parse_command("help")
    assert cmd.name == "help"
    assert cmd.args == ()


def test_help_with_mention_prefix() -> None:
    cmd = parse_command("@offboarding-bot help")
    assert cmd.name == "help"


def test_help_rejects_args() -> None:
    with pytest.raises(BotCommandParseError, match="不需要参数"):
        parse_command("help me")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------
def test_start_valid_username() -> None:
    cmd = parse_command("@offboarding-bot start zhang.san")
    assert cmd.name == "start"
    assert cmd.args == ("zhang.san",)


def test_start_username_with_underscore_dash() -> None:
    cmd = parse_command("start zhang_san-001")
    assert cmd.args == ("zhang_san-001",)


def test_start_missing_arg() -> None:
    with pytest.raises(BotCommandParseError, match="用法"):
        parse_command("start")


def test_start_extra_arg() -> None:
    with pytest.raises(BotCommandParseError, match="用法"):
        parse_command("start zhang.san extra")


@pytest.mark.parametrize(
    "bad",
    [
        "1zhangsan",  # 数字开头
        "zhang!san",  # 特殊字符
        "zhang san",  # 空格 — 会被 tokenize 成两参数（仍报错：用法）
        "",
        "a" * 70,  # 超长
    ],
)
def test_start_rejects_bad_username(bad: str) -> None:
    with pytest.raises(BotCommandParseError):
        parse_command(f"start {bad}".strip())


# ---------------------------------------------------------------------------
# status / report / suggest（共享 flow_id 参数校验）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cmd_name", ["status", "report", "suggest"])
def test_flowid_8char_short_id(cmd_name: str) -> None:
    cmd = parse_command(f"{cmd_name} 8f3a2b1e")
    assert cmd.name == cmd_name
    assert cmd.args == ("8f3a2b1e",)


@pytest.mark.parametrize("cmd_name", ["status", "report", "suggest"])
def test_flowid_full_uuid(cmd_name: str) -> None:
    full = "8f3a2b1e-aaaa-bbbb-cccc-1234567890ab"
    cmd = parse_command(f"{cmd_name} {full}")
    assert cmd.args == (full,)


@pytest.mark.parametrize("cmd_name", ["status", "report", "suggest"])
def test_flowid_rejects_bad_format(cmd_name: str) -> None:
    with pytest.raises(BotCommandParseError, match="flow_id 格式不合法"):
        parse_command(f"{cmd_name} zzz")


@pytest.mark.parametrize("cmd_name", ["status", "report", "suggest"])
def test_flowid_missing(cmd_name: str) -> None:
    with pytest.raises(BotCommandParseError, match="用法"):
        parse_command(cmd_name)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def test_list_default_active() -> None:
    cmd = parse_command("list")
    assert cmd.name == "list"
    assert cmd.args == ("active",)


@pytest.mark.parametrize("flt", ["active", "completed", "stuck"])
def test_list_with_filter(flt: str) -> None:
    cmd = parse_command(f"list {flt}")
    assert cmd.args == (flt,)


def test_list_rejects_unknown_filter() -> None:
    with pytest.raises(BotCommandParseError, match="过滤值不合法"):
        parse_command("list bogus")


# ---------------------------------------------------------------------------
# simulate-timeout / simulate-evidence-missing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cmd_name", ["simulate-timeout", "simulate-evidence-missing"])
def test_simulate_valid(cmd_name: str) -> None:
    cmd = parse_command(f"{cmd_name} 8f3a2b1e device_return")
    assert cmd.name == cmd_name
    assert cmd.args == ("8f3a2b1e", "device_return")


@pytest.mark.parametrize("cmd_name", ["simulate-timeout", "simulate-evidence-missing"])
def test_simulate_missing_node(cmd_name: str) -> None:
    with pytest.raises(BotCommandParseError, match="用法"):
        parse_command(f"{cmd_name} 8f3a2b1e")


def test_simulate_rejects_bad_node_name() -> None:
    with pytest.raises(BotCommandParseError, match="node_name 格式不合法"):
        parse_command("simulate-timeout 8f3a2b1e Device.Return!")


# ---------------------------------------------------------------------------
# 通用：未知命令 / 空输入 / mention 剥离
# ---------------------------------------------------------------------------
def test_unknown_command() -> None:
    with pytest.raises(BotCommandParseError, match="未知命令"):
        parse_command("@offboarding-bot dance")


def test_empty_input() -> None:
    with pytest.raises(BotCommandParseError, match="为空"):
        parse_command("")


def test_only_mention_rejected() -> None:
    """仅 `@offboarding-bot` 整体作为 token → 未知命令报错（外层 strip 已去掉尾空格）。"""
    with pytest.raises(BotCommandParseError, match="未知命令"):
        parse_command("@offboarding-bot")


def test_command_case_insensitive() -> None:
    """命令名应该 case-insensitive（用户可能输 'HELP'）。"""
    cmd = parse_command("HELP")
    assert cmd.name == "help"


def test_all_commands_constant_complete() -> None:
    """ALL_COMMANDS 必须覆盖 8 命令（防忘记加新命令）。"""
    assert set(ALL_COMMANDS) == {
        "start",
        "status",
        "report",
        "suggest",
        "list",
        "help",
        "simulate-timeout",
        "simulate-evidence-missing",
    }
