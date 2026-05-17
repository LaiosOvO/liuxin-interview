#!/usr/bin/env python3
"""Huly Workspace 预建脚本（Phase 8 / HULY-08 配套）。

目标：
- 在 seed 13 个用户之前，确保 Huly workspace `laios` 已存在
- v1 容忍手动 UI 创建（避免 Huly v0.7 createWorkspace API 不稳）
- 如果 workspace 已存在，仅 log + exit 0
- 如果 workspace 不存在且 admin 未提供凭证，友好提示用户手动在 UI 创建

设计决策：
- 不强制实现 createWorkspace（plan 说"避免范围爆炸"）
- 仅做"探测"：尝试用 admin 凭证 selectWorkspace 看是否 200
- 不强制 fail（演示场景手动 UI 创建即可，CI 场景 docker-compose 自动起 huly-stack 已含 workspace）

用法：
    python scripts/seed_huly_workspace.py

环境变量：
    HULY_BRIDGE_URL          (默认 http://localhost:7777)
    HULY_BRIDGE_TOKEN        (必填)
    HULY_ADMIN_EMAIL         (必填)
    HULY_ADMIN_PASSWORD      (必填)
    HULY_WORKSPACE           (默认 laios)

退出码：
    0 - workspace 已存在 / 探测成功
    1 - 探测失败（提示用户手动操作）
    2 - 配置错误（凭证缺失）
"""

from __future__ import annotations

import logging
import os
import sys


def _setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    return logging.getLogger("seed_huly_workspace")


def main() -> int:
    """脚本入口。返回 0 = ok / 1 = workspace 缺 / 2 = 配置错误。"""
    logger = _setup_logger()

    bridge_url = os.environ.get("HULY_BRIDGE_URL", "http://localhost:7777")
    bridge_token = os.environ.get("HULY_BRIDGE_TOKEN", "")
    admin_email = os.environ.get("HULY_ADMIN_EMAIL", "")
    admin_password = os.environ.get("HULY_ADMIN_PASSWORD", "")
    workspace = os.environ.get("HULY_WORKSPACE", "laios")

    if not bridge_token:
        logger.error("缺 HULY_BRIDGE_TOKEN env — 无法探测 sidecar")
        return 2
    if not admin_email or not admin_password:
        logger.warning(
            "未配 HULY_ADMIN_EMAIL / HULY_ADMIN_PASSWORD — 跳过 workspace 探测"
            "（演示场景请确保已通过 Huly UI 手动创建 workspace=%s）",
            workspace,
        )
        return 0

    logger.info("探测 Huly workspace=%s（admin=%s）...", workspace, admin_email)

    # v1：通过 sidecar /healthz 检测 huly_connected 即可。sidecar 已用 admin token
    # 连上 transactor 拿 workspace token，如果连上说明 workspace 存在。
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{bridge_url.rstrip('/')}/healthz")
            if resp.status_code != 200:
                logger.error(
                    "sidecar /healthz 返回 %d；检查 huly-bridge 是否启动",
                    resp.status_code,
                )
                return 1
            data = resp.json()
            if not data.get("huly_connected"):
                logger.error(
                    "sidecar 连 Huly 失败：%s — 请手动在 Huly UI (%s) 创建 workspace='%s' "
                    "并确保 admin 账号 (%s) 在 workspace 内",
                    data.get("last_error", "未知错误"),
                    os.environ.get("HULY_URL", "http://192.168.2.44:8087"),
                    workspace,
                    admin_email,
                )
                return 1

            logger.info(
                "[seed_huly_workspace] ✓ workspace=%s 已存在且 sidecar 已连上 transactor",
                workspace,
            )
            return 0

    except Exception as exc:
        logger.error("探测异常（sidecar 不可达？）: %s", exc)
        logger.error(
            "请手动在 Huly UI (%s) 创建 workspace='%s' 后重试",
            os.environ.get("HULY_URL", "http://192.168.2.44:8087"),
            workspace,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
