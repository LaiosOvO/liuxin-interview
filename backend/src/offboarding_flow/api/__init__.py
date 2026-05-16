"""FastAPI 路由模块。"""

from .auth import router as auth_router
from .flows import router as flows_router
from .health import router as health_router
from .mattermost_webhook import router as mattermost_webhook_router
from .nodes import router as nodes_router

__all__ = [
    "auth_router",
    "flows_router",
    "health_router",
    "mattermost_webhook_router",
    "nodes_router",
]
