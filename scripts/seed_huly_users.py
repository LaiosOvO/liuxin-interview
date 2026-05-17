#!/usr/bin/env python3
"""Huly Users Seed 脚本（Phase 8 / HULY-08）。

把业务 DB 中的 13 个 user 一次性同步到 Huly：
- 调 sidecar `POST /api/admin/signup_join`（双 token 鉴权：BRIDGE + ADMIN）
- 每个 user 走 admin login → createInvite → signUpJoin 链路（避开 Pitfall #1）
- 全流程幂等：已存在的账号会被 sidecar 返回 `skipped=true`

设计要点（CLAUDE.md §3.4 幂等 + §3.5 凭证安全）：
- 只读业务 DB（不修改）
- 调 sidecar HTTP（不直接连 Huly transactor）
- 凭证全走 .env 注入（HULY_USER_PASSWORD / HULY_BRIDGE_TOKEN / HULY_ADMIN_TOKEN）
- 中文 log + structured 输出 summary

用法：
    # dry-run 预览（不发请求，只打印每个 user 将做什么）
    python scripts/seed_huly_users.py --dry-run

    # 真 seed
    python scripts/seed_huly_users.py

    # docker 内
    docker exec offboarding-backend uv run python /app/scripts/seed_huly_users.py

环境变量（必填，从 .env）:
    HULY_BRIDGE_URL          (默认 http://huly-bridge:7777)
    HULY_BRIDGE_TOKEN        sidecar 通信 token
    HULY_ADMIN_TOKEN         sidecar admin 路由二级 token
    HULY_USER_PASSWORD       13 个 seeded user 的默认密码（演示用）

退出码:
    0 - 全部成功（含 skipped）
    1 - 至少 1 个 user failed
    2 - 配置错误
    3 - sidecar 5xx（停止后续 seed）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass

import httpx

# 让本脚本能 import backend/src/offboarding_flow
_BACKEND_SRC = os.path.join(os.path.dirname(__file__), "..", "backend", "src")
if os.path.isdir(_BACKEND_SRC):
    sys.path.insert(0, _BACKEND_SRC)


logger = logging.getLogger("seed_huly_users")


# ---------------------------------------------------------------------------
# 演示约定（C-1）：所有 seed 用户的 Huly email 用 `{username}@demo.local`
# 与 sidecar src/im.ts:DEMO_EMAIL_DOMAIN 同源
# ---------------------------------------------------------------------------
DEMO_EMAIL_DOMAIN = "demo.local"


@dataclass(frozen=True)
class SeedTarget:
    """单个待 seed 的 user 数据（来自业务 DB users 表）。"""

    username: str
    email: str
    first_name: str
    last_name: str
    role: str  # "USER" / "MAINTAINER" / "GUEST"（Huly workspace role；默认 USER）


@dataclass(frozen=True)
class SeedResult:
    """单个 user 的 seed 结果（汇总到 Summary）。"""

    username: str
    status: str  # "seeded" / "skipped" / "failed"
    account_uuid: str | None
    error: str | None


# ---------------------------------------------------------------------------
# 业务 DB 取数
# ---------------------------------------------------------------------------


async def _load_users_from_db() -> list[SeedTarget]:
    """从业务 DB users 表读所有用户，转 SeedTarget 列表（按 username 字典序）。"""
    from sqlalchemy import select

    from offboarding_flow.state_store.models import User  # type: ignore[import-untyped]
    from offboarding_flow.state_store.session import get_sessionmaker  # type: ignore[import-untyped]

    sm = get_sessionmaker()
    async with sm() as session:
        rows = (
            (await session.execute(select(User).order_by(User.username)))
            .scalars()
            .all()
        )

    targets: list[SeedTarget] = []
    for u in rows:
        # email 用 demo.local 域；display_name 拆 first/last
        display = (u.display_name or u.username).strip()
        if " " in display:
            first, last = display.split(" ", 1)
        else:
            first, last = display, ""
        targets.append(
            SeedTarget(
                username=u.username,
                email=f"{u.username}@{DEMO_EMAIL_DOMAIN}",
                first_name=first,
                last_name=last,
                role="USER",
            )
        )
    return targets


# ---------------------------------------------------------------------------
# sidecar 通信
# ---------------------------------------------------------------------------


def _signup_join_request_body(target: SeedTarget, password: str) -> dict:
    """构造 sidecar /api/admin/signup_join 请求体。"""
    return {
        "username": target.username,
        "email": target.email,
        "password": password,
        "first_name": target.first_name,
        "last_name": target.last_name,
        "role": target.role,
    }


async def _seed_one(
    client,  # httpx.AsyncClient
    *,
    bridge_url: str,
    bridge_token: str,
    admin_token: str,
    target: SeedTarget,
    password: str,
) -> SeedResult:
    """单个 user 调 sidecar 完成 signup_join。

    返回 SeedResult；调用方汇总 Summary。
    """
    url = f"{bridge_url.rstrip('/')}/api/admin/signup_join"
    headers = {
        "X-Bridge-Token": bridge_token,
        "X-Admin-Token": admin_token,
        "Content-Type": "application/json",
    }

    try:
        resp = await client.post(
            url, json=_signup_join_request_body(target, password), headers=headers
        )
    except Exception as exc:
        # 网络层失败 → failed（不抛，让 Summary 记录）
        return SeedResult(
            username=target.username,
            status="failed",
            account_uuid=None,
            error=f"网络错误: {exc}",
        )

    if 500 <= resp.status_code < 600:
        # 5xx → 抛异常让外层立即停止
        raise RuntimeError(
            f"sidecar 5xx (status={resp.status_code}): {resp.text[:200]}"
        )

    if resp.status_code == 200:
        body = resp.json()
        data = body.get("data") or {}
        skipped = bool(data.get("skipped", False))
        return SeedResult(
            username=target.username,
            status="skipped" if skipped else "seeded",
            account_uuid=data.get("account_uuid"),
            error=None,
        )

    # 4xx → failed（log + 累加）
    try:
        body = resp.json()
        err = body.get("error") or body.get("code") or resp.text
    except Exception:
        err = resp.text or f"HTTP {resp.status_code}"
    return SeedResult(
        username=target.username,
        status="failed",
        account_uuid=None,
        error=f"HTTP {resp.status_code}: {err}",
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def _async_main(args: argparse.Namespace) -> int:
    """异步主流程。返回 exit code。"""
    bridge_url = args.bridge_url or os.environ.get(
        "HULY_BRIDGE_URL", "http://huly-bridge:7777"
    )
    bridge_token = args.bridge_token or os.environ.get("HULY_BRIDGE_TOKEN", "")
    admin_token = args.admin_token or os.environ.get("HULY_ADMIN_TOKEN", "")
    password = args.password or os.environ.get("HULY_USER_PASSWORD", "")

    if not bridge_token:
        logger.error("缺 HULY_BRIDGE_TOKEN env / --bridge-token")
        return 2
    if not admin_token:
        logger.error("缺 HULY_ADMIN_TOKEN env / --admin-token")
        return 2
    if not password:
        logger.error("缺 HULY_USER_PASSWORD env / --password")
        return 2

    # 1. 取业务 DB 用户
    try:
        targets = await _load_users_from_db()
    except Exception as exc:
        logger.error("读业务 DB users 表失败: %s", exc)
        return 2

    if not targets:
        logger.warning("业务 DB users 表为空 — 请先跑 seed_demo_data.py")
        return 0

    logger.info(
        "[seed_huly_users] 准备 seed %d 个用户到 Huly（workspace 路由通过 sidecar %s）",
        len(targets),
        bridge_url,
    )

    if args.dry_run:
        logger.info("[seed_huly_users] DRY-RUN — 不发请求，仅预览：")
        for t in targets:
            logger.info(
                "  · %s → email=%s first=%s last=%s role=%s",
                t.username,
                t.email,
                t.first_name,
                t.last_name,
                t.role,
            )
        logger.info("[seed_huly_users] DRY-RUN 完成（共 %d 个目标）", len(targets))
        return 0

    # 2. 调 sidecar 逐个 seed（5xx 立即停止）
    results: list[SeedResult] = []
    seeded = 0
    skipped = 0
    failed = 0

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for t in targets:
            try:
                r = await _seed_one(
                    client,
                    bridge_url=bridge_url,
                    bridge_token=bridge_token,
                    admin_token=admin_token,
                    target=t,
                    password=password,
                )
            except RuntimeError as exc:
                # 5xx → 停止
                logger.error(
                    "[seed_huly_users] sidecar 5xx 抛出，停止后续 seed：%s", exc
                )
                # 当前已完成的 results 计入
                for r0 in results:
                    if r0.status == "seeded":
                        seeded += 1
                    elif r0.status == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                logger.error(
                    "[seed_huly_users] 中断 summary: seeded=%d skipped=%d failed=%d "
                    "(剩 %d 未尝试)",
                    seeded,
                    skipped,
                    failed,
                    len(targets) - len(results),
                )
                return 3

            results.append(r)
            if r.status == "seeded":
                seeded += 1
                logger.info(
                    "[seed_huly_users] %s 新建 account_uuid=%s",
                    r.username,
                    r.account_uuid,
                )
            elif r.status == "skipped":
                skipped += 1
                logger.info(
                    "[seed_huly_users] %s 已存在，跳过 (account_uuid=%s)",
                    r.username,
                    r.account_uuid,
                )
            else:
                failed += 1
                logger.warning("[seed_huly_users] %s 失败: %s", r.username, r.error)

    logger.info(
        "[seed_huly_users] === DONE: seeded=%d, skipped=%d, failed=%d (total=%d) ===",
        seeded,
        skipped,
        failed,
        len(targets),
    )

    return 0 if failed == 0 else 1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把业务 DB 用户批量同步到 Huly（Phase 8 / HULY-08）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印每个 user 将做什么，不发请求",
    )
    parser.add_argument(
        "--bridge-url",
        default=None,
        help="sidecar URL（默认 $HULY_BRIDGE_URL 或 http://huly-bridge:7777）",
    )
    parser.add_argument(
        "--bridge-token",
        default=None,
        help="sidecar BRIDGE_TOKEN（默认 $HULY_BRIDGE_TOKEN）",
    )
    parser.add_argument(
        "--admin-token",
        default=None,
        help="sidecar ADMIN_TOKEN（默认 $HULY_ADMIN_TOKEN）",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="seeded user 的默认密码（默认 $HULY_USER_PASSWORD）",
    )
    return parser


def main() -> int:
    """脚本入口（同步包装 asyncio）。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    args = _build_arg_parser().parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
