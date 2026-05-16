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

    # Phase 4 Slice 4B: Mattermost @bot 入口（PRD §7.2 + §16）
    mattermost_url: str = "http://192.168.2.44:8065"
    mattermost_team: str = "laios"
    mattermost_bot_username: str = "offboarding-bot"
    mattermost_bot_user_id: str = "__from_bot_create__"
    mattermost_bot_token: str = "changeme_in_real_env"
    # Outgoing Webhook token — Mattermost 后台创建 Outgoing Webhook 时生成；用于校验入站请求合法性
    mattermost_outgoing_webhook_token: str = "changeme_in_real_env"
    # HTTP timeout（秒）— Mattermost 内网调用，给短超时；避免节点函数阻塞
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
    return settings


def reload_settings() -> Settings:
    """测试用：清缓存重新加载。"""
    get_settings.cache_clear()
    return get_settings()
