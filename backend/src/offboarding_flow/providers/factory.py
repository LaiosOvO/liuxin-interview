"""Provider 工厂 — Registry 配置化 + 按 settings 选择实现。

设计（Phase 8 收尾抽象升级）：
- 内置 6 个 IM/Doc provider 通过 `_BUILTIN_*_REGISTRY` 字典声明 `"name" → "module.path:ClassName"`
- 外部包可通过 `register_im_provider("custom_slack", "my_co.slack:SlackProvider")` 注册新平台
- factory 走 `importlib.import_module` lazy import + 反射实例化（构造签名约定：无参 或 (settings,)）
- 加新平台 = 写 1 个 Provider 类 + 调 1 行 register_*_provider；**不改 factory.py**
- env: DOC_PROVIDER=outline / IM_PROVIDER=mattermost 选键名；未知键报错时打印可用清单
"""

from __future__ import annotations

import importlib
import inspect
import logging
from functools import lru_cache

from offboarding_flow.config import get_settings

from .base import DocProvider, IMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry — 内置 6 个 provider 的 "name → module:Class" 声明式注册表
# ---------------------------------------------------------------------------

# Doc providers — 协作文档平台
_BUILTIN_DOC_REGISTRY: dict[str, str] = {
    "outline": "offboarding_flow.providers.outline_provider:OutlineProvider",
    "lark": "offboarding_flow.providers.lark_provider:LarkDocsProvider",
    "wecom": "offboarding_flow.providers.wecom_provider:WeComDocProvider",
    "dingtalk": "offboarding_flow.providers.dingtalk_provider:DingTalkDocProvider",
    "huly": "offboarding_flow.providers.huly_doc_provider:HulyDocProvider",
}

# IM providers — 即时通讯 / Bot 平台
_BUILTIN_IM_REGISTRY: dict[str, str] = {
    "mattermost": "offboarding_flow.providers.mattermost_provider:MattermostProvider",
    "lark": "offboarding_flow.providers.lark_provider:LarkIMProvider",
    "wecom": "offboarding_flow.providers.wecom_provider:WeComIMProvider",
    "dingtalk": "offboarding_flow.providers.dingtalk_provider:DingTalkIMProvider",
    "huly": "offboarding_flow.providers.huly_im_provider:HulyIMProvider",
}

# 可扩展注册表 — 外部包通过 register_*_provider() API 写入
_doc_registry: dict[str, str] = dict(_BUILTIN_DOC_REGISTRY)
_im_registry: dict[str, str] = dict(_BUILTIN_IM_REGISTRY)


# ---------------------------------------------------------------------------
# 外部注册 API — 让自定义平台无需改 factory 即可接入
# ---------------------------------------------------------------------------


def register_doc_provider(name: str, dotted_path: str) -> None:
    """注册一个新 Doc Provider。

    Args:
        name: 用在 `.env DOC_PROVIDER=xxx` 的 key（小写）
        dotted_path: "module.path:ClassName" 形式（与 importlib pattern 一致）

    Example:
        >>> register_doc_provider("my_slack", "my_company.providers.slack:SlackDocs")
        # 之后 DOC_PROVIDER=my_slack 就能用，且 factory.py 0 改动
    """
    key = name.strip().lower()
    if not key:
        raise ValueError("Provider name 不能为空")
    if ":" not in dotted_path:
        raise ValueError(f"dotted_path 必须是 'module.path:Class' 格式，收到: {dotted_path}")
    _doc_registry[key] = dotted_path
    get_doc_provider.cache_clear()
    logger.info("[providers] 注册新 doc provider: %s → %s", key, dotted_path)


def register_im_provider(name: str, dotted_path: str) -> None:
    """注册一个新 IM Provider。"""
    key = name.strip().lower()
    if not key:
        raise ValueError("Provider name 不能为空")
    if ":" not in dotted_path:
        raise ValueError(f"dotted_path 必须是 'module.path:Class' 格式，收到: {dotted_path}")
    _im_registry[key] = dotted_path
    get_im_provider.cache_clear()
    logger.info("[providers] 注册新 IM provider: %s → %s", key, dotted_path)


def available_doc_providers() -> list[str]:
    """列出当前所有已注册的 doc provider name（供 admin / healthcheck 查）。"""
    return sorted(_doc_registry.keys())


def available_im_providers() -> list[str]:
    """列出当前所有已注册的 IM provider name。"""
    return sorted(_im_registry.keys())


# ---------------------------------------------------------------------------
# Lazy import + 反射实例化
# ---------------------------------------------------------------------------


def _instantiate(dotted_path: str) -> object:
    """按 'module.path:Class' lazy import + 实例化。

    构造签名约定：
    - 无参 `Class()` — 多数 provider 直接读 settings
    - 单参 `Class(settings)` — 若构造期需要 inject settings（HulyProvider 等）
    工厂自动按 inspect 决定调用方式，新 provider 作者不用关心顺序。
    """
    module_path, class_name = dotted_path.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(
            f"无法 import provider 模块 '{module_path}'：{e}。"
            f"检查包是否已安装 / dotted_path 是否拼写正确。"
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(
            f"模块 '{module_path}' 没有名为 '{class_name}' 的类。" f"检查 dotted_path 是否正确。"
        )
    if not inspect.isclass(cls):
        raise TypeError(f"'{dotted_path}' 解析到的是 {type(cls).__name__}，不是类。")
    sig = inspect.signature(cls.__init__)
    # __init__(self, ...) — self 不算
    non_self_params = [
        p for n, p in sig.parameters.items() if n != "self" and p.kind != p.VAR_KEYWORD
    ]
    if not non_self_params:
        return cls()
    # 至少有一个非 self 参数 → 注入 settings
    return cls(get_settings())


# ---------------------------------------------------------------------------
# 单例工厂 — settings.doc_provider / im_provider 决定选哪个
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_doc_provider() -> DocProvider:
    settings = get_settings()
    name = (settings.doc_provider or "outline").lower()
    if name not in _doc_registry:
        raise ValueError(
            f"未知 DOC_PROVIDER: {name}。可用：{available_doc_providers()}。"
            f"或通过 register_doc_provider('{name}', 'module:Class') 注册。"
        )
    dotted = _doc_registry[name]
    logger.info("[providers] 选用 doc provider: %s (%s)", name, dotted)
    instance = _instantiate(dotted)
    return instance  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_im_provider() -> IMProvider:
    settings = get_settings()
    name = (settings.im_provider or "mattermost").lower()
    if name not in _im_registry:
        raise ValueError(
            f"未知 IM_PROVIDER: {name}。可用：{available_im_providers()}。"
            f"或通过 register_im_provider('{name}', 'module:Class') 注册。"
        )
    dotted = _im_registry[name]
    logger.info("[providers] 选用 IM provider: %s (%s)", name, dotted)
    instance = _instantiate(dotted)
    return instance  # type: ignore[return-value]


def reset_providers() -> None:
    """测试用：清单例缓存 + 重置 registry 到内置默认值。"""
    get_doc_provider.cache_clear()
    get_im_provider.cache_clear()
    _doc_registry.clear()
    _doc_registry.update(_BUILTIN_DOC_REGISTRY)
    _im_registry.clear()
    _im_registry.update(_BUILTIN_IM_REGISTRY)


__all__ = [
    "available_doc_providers",
    "available_im_providers",
    "get_doc_provider",
    "get_im_provider",
    "register_doc_provider",
    "register_im_provider",
    "reset_providers",
]
