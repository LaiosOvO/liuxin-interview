#!/usr/bin/env python3
"""演示组织数据 Seed 脚本（Phase 4 Slice 4D — SEED-01/02/03）。

落地 PRD §9.1：
- 5 个 team：engineering / hr / it / finance / legal
- 8 个测试账号：zhang.san / li.si / wang.wu / hr.alice / hr.bob / it.charlie / fin.david / legal.eve
- 每个 user 写 Custom Attributes：employee_id / department / role / manager_email
- 启动校验 Mattermost AllowedUntrustedInternalConnections（PITFALLS #7）
- 幂等：ensure_team / ensure_user — GET-then-create（PITFALLS #11）
- 可选：--create-flow 跑完后用 zhang.san 起一个 standard_offboarding 流程

依赖：mattermostautodriver（同步 SDK，seed 一次性脚本无需 async）

用法：
    # 仅 seed（不起流程）
    python scripts/seed_demo_data.py --mm-url http://192.168.2.44:8065 --bot-token $MATTERMOST_BOT_TOKEN

    # seed + 一键起 zhang.san 流程触发首封邮件
    python scripts/seed_demo_data.py --create-flow

环境变量回退（CLI 未传时用）:
    MATTERMOST_URL / MATTERMOST_BOT_TOKEN / MATTERMOST_TEAM
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass

logger = logging.getLogger("seed_demo_data")


# ---------------------------------------------------------------------------
# 8 测试账号 + 5 team 元数据（PRD §9.1.2）
# ---------------------------------------------------------------------------
TEAMS = [
    ("engineering", "研发部"),
    ("hr", "人力资源部"),
    ("it", "IT 运维部"),
    ("finance", "财务部"),
    ("legal", "法务部"),
]


@dataclass(frozen=True)
class DemoUser:
    username: str
    first_name: str
    last_name: str
    role: str  # employee / manager / hr / it / finance / legal
    employee_id: str
    team: str
    manager_email: str  # 关系链；演示用 @demo.local 域


USERS: list[DemoUser] = [
    DemoUser("zhang.san", "三", "张", "employee", "EMP001", "engineering", "li.si@demo.local"),
    DemoUser("li.si", "四", "李", "manager", "EMP002", "engineering", "wang.wu@demo.local"),
    DemoUser("wang.wu", "五", "王", "manager", "EMP003", "engineering", ""),
    DemoUser("hr.alice", "Alice", "HR", "hr", "EMP004", "hr", "hr.bob@demo.local"),
    DemoUser("hr.bob", "Bob", "HR", "hr", "EMP005", "hr", ""),
    DemoUser("it.charlie", "Charlie", "IT", "it", "EMP006", "it", ""),
    DemoUser("fin.david", "David", "Fin", "finance", "EMP007", "finance", ""),
    DemoUser("legal.eve", "Eve", "Legal", "legal", "EMP008", "legal", ""),
]

# 演示统一密码（不重要，Mattermost demo 用；不写真实密码）
DEMO_PASSWORD = "DemoP@ssw0rd!2026"


def ensure_team(driver, name: str, display_name: str) -> dict:
    """幂等创建 team。已存在则返回原 team。"""
    try:
        team = driver.teams.get_team_by_name(name)
        logger.info("[seed] team %s exists (id=%s)", name, team.get("id"))
        return team
    except Exception:
        logger.info("[seed] creating team %s ...", name)
        return driver.teams.create_team(
            {"name": name, "display_name": display_name, "type": "O"}
        )


def ensure_user(driver, user: DemoUser) -> dict:
    """幂等创建 user。已存在则返回原 user。"""
    try:
        existing = driver.users.get_user_by_username(user.username)
        logger.info("[seed] user %s exists (id=%s)", user.username, existing.get("id"))
        return existing
    except Exception:
        logger.info("[seed] creating user %s ...", user.username)
        return driver.users.create_user(
            {
                "username": user.username,
                "email": f"{user.username}@demo.local",  # demo 域；真发邮件由 envelope 覆写到 DEMO_INBOX
                "password": DEMO_PASSWORD,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "position": _role_position(user.role),
            }
        )


def _role_position(role: str) -> str:
    return {
        "employee": "员工",
        "manager": "经理",
        "hr": "HR 专员",
        "it": "IT 运维",
        "finance": "财务专员",
        "legal": "法务合规",
    }.get(role, "成员")


def ensure_team_membership(driver, team_id: str, user_id: str, username: str) -> None:
    """幂等添加 user 到 team。"""
    try:
        driver.teams.add_user_to_team(team_id, {"team_id": team_id, "user_id": user_id})
        logger.info("[seed] add %s to team %s", username, team_id[:8])
    except Exception as exc:
        # 重复添加 Mattermost 返回 400，吞掉
        logger.debug("[seed] add_user_to_team likely already member: %s", exc)


def set_custom_attributes(driver, user_id: str, user: DemoUser) -> None:
    """写入 4 个 Custom Attribute（employee_id / department / role / manager_email）。

    Mattermost Custom Profile Attributes API 路径：
        PATCH /api/v4/users/{user_id}/custom_attributes/values
    需后台先启用 Custom Profile Attributes 特性。
    """
    attrs = {
        "employee_id": user.employee_id,
        "department": user.team,
        "role": user.role,
        "manager_email": user.manager_email,
    }
    try:
        # mattermostautodriver 版本可能未直接暴露 custom_attributes — 用 raw HTTP
        driver.client.make_request(
            "patch",
            f"/users/{user_id}/custom_attributes/values",
            data=attrs,
        )
        logger.info("[seed] set custom attrs for %s", user.username)
    except Exception as exc:
        logger.warning(
            "[seed] set custom attrs failed for %s (Custom Profile Attributes 是否启用？): %s",
            user.username,
            exc,
        )


def verify_untrusted_connections(driver) -> None:
    """启动校验 Mattermost 配置（PITFALLS #7）。

    服务端配置 ServiceSettings.AllowedUntrustedInternalConnections 必须含本机 IP，
    否则 Interactive Message action callback 会被 SSRF 防护拦截。
    """
    try:
        cfg = driver.system.get_client_config_old()
        # client config 不暴露 AllowedUntrustedInternalConnections，提示用户手动 verify
        logger.info(
            "[seed] Mattermost server version=%s — 请确认管理员后台已配置 "
            "AllowedUntrustedInternalConnections 含本系统 IP（PITFALLS #7）",
            cfg.get("Version", "unknown"),
        )
    except Exception as exc:
        logger.warning("[seed] could not fetch Mattermost server config: %s", exc)


def main() -> int:
    """脚本入口。返回 0 = success / 非 0 = error。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Seed demo data into Mattermost")
    parser.add_argument(
        "--mm-url",
        default=os.environ.get("MATTERMOST_URL"),
        help="Mattermost URL (default: $MATTERMOST_URL)",
    )
    parser.add_argument(
        "--bot-token",
        default=os.environ.get("MATTERMOST_BOT_TOKEN"),
        help="Bot Personal Access Token (default: $MATTERMOST_BOT_TOKEN)",
    )
    parser.add_argument(
        "--create-flow",
        action="store_true",
        help="seed 完成后自动起一个 zhang.san 离职流程触发首封邮件",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("FLOW_API_URL", "http://localhost:8000"),
        help="本系统 FastAPI URL（--create-flow 时用）",
    )
    args = parser.parse_args()

    if not args.mm_url or not args.bot_token:
        logger.error(
            "缺少 --mm-url / --bot-token（也可通过 MATTERMOST_URL / MATTERMOST_BOT_TOKEN 环境变量提供）"
        )
        return 2
    if args.bot_token.startswith("changeme_in_real_env"):
        logger.error(
            "MATTERMOST_BOT_TOKEN 仍是占位值，请在 Mattermost 后台创建 Bot 账号后填真值到 .env"
        )
        return 2

    try:
        from mattermostautodriver import Driver
    except ImportError:
        logger.error("缺少 mattermostautodriver 依赖。请 cd backend && uv sync")
        return 2

    driver = Driver(
        {
            "url": args.mm_url.replace("http://", "").replace("https://", "").split(":")[0],
            "port": int(args.mm_url.rsplit(":", 1)[-1]) if ":" in args.mm_url.replace("http://", "") else 8065,
            "scheme": "https" if args.mm_url.startswith("https") else "http",
            "token": args.bot_token,
        }
    )
    driver.login()
    verify_untrusted_connections(driver)

    # 1. teams
    team_id_by_name: dict[str, str] = {}
    for name, display in TEAMS:
        team = ensure_team(driver, name, display)
        team_id_by_name[name] = team["id"]

    # 2. users + memberships + custom attrs
    user_id_by_username: dict[str, str] = {}
    for u in USERS:
        created = ensure_user(driver, u)
        uid = created["id"]
        user_id_by_username[u.username] = uid
        ensure_team_membership(driver, team_id_by_name[u.team], uid, u.username)
        set_custom_attributes(driver, uid, u)

    logger.info("[seed] === DONE: %d teams + %d users ===", len(TEAMS), len(USERS))

    # 3. 可选：起一个流程
    if args.create_flow:
        try:
            import httpx

            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{args.api_url.rstrip('/')}/api/flows",
                    json={"employee_id": "zhang.san"},
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info(
                    "[seed] created demo flow id=%s (POST %s)",
                    data.get("data", {}).get("id"),
                    f"{args.api_url}/api/flows",
                )
        except Exception as exc:
            logger.warning(
                "[seed] --create-flow 调用失败（确认 flow-api 在 %s 启动）: %s",
                args.api_url,
                exc,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
