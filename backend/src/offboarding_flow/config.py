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

from pydantic import Field, computed_field, field_validator
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
    # 空字符串视作 None（docker-compose 默认替换会传 "" 而非 unset）
    demo_timeout_override_hours: float | None = Field(default=None)

    @field_validator("demo_timeout_override_hours", mode="before")
    @classmethod
    def _empty_str_as_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

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

    # Outline 协作文档（meeting-* 命令用）
    outline_url: str = "http://192.168.2.44:3001"  # 外部访问 + Outline 内部使用
    outline_api_token: str = Field(
        default="changeme_when_outline_admin_created", validate_default=False
    )

    # Provider 路由：DOC_PROVIDER / IM_PROVIDER (单)，IM_PROVIDERS (复，5.3 多 listener 并存)
    doc_provider: str = "outline"  # outline | lark | wecom | dingtalk | huly
    im_provider: str = "mattermost"  # 兼容字段 — IM_PROVIDERS 为空时回退到此
    im_providers: str = (
        ""  # 复数，逗号分隔 "mattermost,huly" 多 listener 并存；空则用 im_provider 单值
    )

    # Lark / 飞书（DOC_PROVIDER=lark 或 IM_PROVIDER=lark 时用）
    lark_base_url: str = "https://open.feishu.cn"  # 国际版改 https://open.larksuite.com
    lark_app_id: str = Field(default="changeme_lark_app_id", validate_default=False)
    lark_app_secret: str = Field(default="changeme_lark_app_secret", validate_default=False)
    lark_docs_folder_token: str = ""  # 文档存放根目录 token（可选）

    # 企业微信
    wecom_corp_id: str = ""
    wecom_corp_secret: str = ""
    wecom_agent_id: str = ""

    # 钉钉
    dingtalk_app_key: str = ""
    dingtalk_app_secret: str = ""

    # Huly Provider（Phase 8 B-full 重构 — Python 直连 REST，去 huly-bridge sidecar）
    # 业务流程：login(admin_email, admin_password) → selectWorkspace(workspace_url)
    # → 后续所有 Tx 走 transactor REST /api/v1/*
    huly_url: str = "http://192.168.2.44:8087"  # Huly Front UI（也是 nginx 入口）
    huly_accounts_url: str = "http://192.168.2.44:8087/_accounts"  # Account RPC
    huly_workspace: str = "laios"  # workspaceUrl name
    huly_admin_email: str = ""  # admin 账号 email（必须已有 social id）
    huly_admin_password: str = ""  # admin 密码（敏感，仅 .env 注入）
    # 业务通信走 chunter Channel（DM 降级为「每员工一个 Channel」+ bot 是 member）
    # B-full-channel: 新建 DM 后立即 add ChatMessage server 端有 join 同步问题，绕开
    huly_user_channel_prefix: str = "dm-"  # 每员工 channel 命名前缀（dm-zhangsan）
    # HTTP 超时（Huly REST + Account RPC 通用）
    huly_http_timeout: float = 15.0

    # Phase 8 / Plan 07 — MCP server（流程 MCP 化，MCP-01..06）
    # MCP_ALLOW_WRITE 默认 false — 防 LLM 误推进流程（PRD §15.3 AI 边界红线 + RESEARCH Pitfall #8）
    # 启用需显式 env MCP_ALLOW_WRITE=true；write tools 在启动期判 env 真禁用（不是只在描述里写）
    mcp_allow_write: bool = Field(default=False)
    # HTTP 模式监听端口（仅 mount 到 FastAPI 时不直接占用，runner.py 直起 http server 时占用）
    mcp_http_port: int = 7788
    # 是否在 FastAPI 内 mount MCP HTTP /mcp/* 路径（默认 false 不影响现有 backend；
    # 演示/远程 LLM 客户端用时切 true，避免起独立容器）
    mcp_http_mounted: bool = False

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
