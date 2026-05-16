"""全局配置 — 从 .env / 环境变量读取（Plan 05）。

关键约定：
- 用 BaseSettings 不要 dotenv 手动 load
- get_settings() 用 lru_cache 单例（FastAPI Depends 友好）
- postgres_dsn_sync 是 asyncpg DSN 去掉 +asyncpg → alembic offline 用
- 启动 log 显式打印 APP_MODE（PITFALLS #10 防上线没切回 prod）
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置（从 .env 注入）。"""

    # 应用基础
    app_mode: Literal["demo", "prod"] = "demo"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    app_version: str = "0.1.0"

    # 数据库
    postgres_password: str = "changeme_in_real_env"
    postgres_dsn: str = (
        "postgresql+asyncpg://flow:changeme_in_real_env@offboarding-postgres:5432/offboarding"
    )
    langgraph_pg_conninfo: str = (
        "postgres://flow:changeme_in_real_env@offboarding-postgres:5432/offboarding"
    )

    # Redis（Phase 3 鉴权才真用，Phase 1 仅 health check）
    redis_url: str = "redis://offboarding-redis:6379/0"

    # 部署 URL（R1 待 Phase 6 修正 — 当前保持与原 .env.example 一致）
    deeplink_base_url: str = "http://192.168.2.44:3000"

    # Phase 3: 鉴权 / JWT / Session
    jwt_secret: str = Field(default="changeme_in_real_env", validate_default=False)
    token_expiry_hours: int = 24
    session_expiry_hours: int = 24
    https_enabled: bool = False
    session_cookie_name: str = "offboarding_session"

    # Phase 4.5: AutoNode 外部归档服务（PRD §18 加分项）
    archive_service_url: str = "http://mock-archive-service:5000/archive"
    archive_service_timeout_seconds: float = 8.0
    archive_service_max_retries: int = 3

    # Phase 6: 节点超时扫描（NOTI-05 + TIMEOUT-01 — PRD §17.1）
    # 默认 24h SLA；演示快速触发用 DEMO_TIMEOUT_OVERRIDE_HOURS（如 0.05 ≈ 3 分钟）
    # DEMO_TIMEOUT_OVERRIDE_HOURS 仅在 app_mode=demo 时生效，prod 永远走 NODE_TIMEOUT_HOURS
    node_timeout_hours: float = 24.0
    demo_timeout_override_hours: float | None = None
    # 扫描频率：默认 60s 扫一次（与 outbox_drain 心跳一致量级）
    timeout_scan_interval_seconds: float = 60.0

    # Phase 4 / Slice 4C: LLM (GLM via openai 兼容接口) — LLM-01..06
    glm_api_key: str = Field(default="changeme_in_real_env", validate_default=False)
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    glm_model: str = "glm-4.6"  # 演示低成本可改 glm-4-flash
    glm_timeout_seconds: float = 8.0  # PITFALLS #22 — asyncio.timeout(8)

    # Phase 4 / Slice 4A: 通知 — SMTP / 演示模式收件箱（PRD §7.4.3 + PITFALLS #14/#15）
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_use_ssl: bool = True  # QQ 强制 SSL，不是 STARTTLS
    smtp_user: str = "changeme_in_real_env@qq.com"
    smtp_password: str = Field(
        default="changeme_in_real_env_16char_authcode",
        validate_default=False,
    )
    smtp_from_name: str = "离职流程 Bot"
    # 演示模式所有邮件覆写到此地址（PRD §7.4.1）
    demo_inbox: str = "changeme_in_real_env@qq.com"

    # Phase 4 / Slice 4B: Mattermost @bot 入口（PRD §7.2 + §16）
    mattermost_url: str = "http://192.168.2.44:8065"
    mattermost_team: str = "laios"
    mattermost_bot_username: str = "offboarding-bot"
    mattermost_bot_user_id: str = "__from_bot_create__"
    mattermost_bot_token: str = "changeme_in_real_env"
    # Outgoing Webhook token — Mattermost 后台创建 Outgoing Webhook 时生成
    mattermost_outgoing_webhook_token: str = "changeme_in_real_env"
    # HTTP timeout（秒）— Mattermost 内网调用，给短超时
    mattermost_http_timeout: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @computed_field  # type: ignore[misc]
    @property
    def postgres_dsn_sync(self) -> str:
        """sync DSN 用于 alembic offline 模式（去掉 +asyncpg 后缀）。"""
        return self.postgres_dsn.replace("+asyncpg", "")

    @computed_field  # type: ignore[misc]
    @property
    def is_demo(self) -> bool:
        return self.app_mode == "demo"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例 Settings — 启动后冻结。"""
    settings = Settings()
    logger = logging.getLogger(__name__)
    # PITFALLS #10: 启动时显式打印 APP_MODE，防上线没切回 prod
    logger.warning("=" * 60)
    logger.warning("APP_MODE = %s", settings.app_mode.upper())
    logger.warning("APP_VERSION = %s", settings.app_version)
    logger.warning("LOG_LEVEL = %s", settings.log_level)
    logger.warning("=" * 60)
    # Phase 3: 生产模式 JWT_SECRET 校验 — 禁止默认占位值上线
    if settings.app_mode == "prod" and settings.jwt_secret in {
        "changeme_in_real_env",
        "changeme_in_real_env_openssl_rand_hex_32",
    }:
        raise RuntimeError("生产模式（APP_MODE=prod）必须设置 JWT_SECRET（openssl rand -hex 32）")
    # Phase 4: 生产模式 SMTP_PASSWORD 校验 — 禁止占位 16char 授权码上线（PITFALLS #10）
    if settings.app_mode == "prod" and settings.smtp_password.startswith("changeme_in_real_env"):
        raise RuntimeError("生产模式（APP_MODE=prod）必须设置 SMTP_PASSWORD（QQ 邮箱 16 位授权码）")
    return settings


def reload_settings() -> Settings:
    """测试用：清缓存重新加载。"""
    get_settings.cache_clear()
    return get_settings()
