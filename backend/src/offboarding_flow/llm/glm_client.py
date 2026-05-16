"""GLM client — 用 openai 包指向智谱 base_url（LLM-01 + STACK.md §4.6）。

约定:
- `openai` 1.x AsyncOpenAI（异步）
- base_url 默认 `https://open.bigmodel.cn/api/paas/v4/`（智谱 OpenAI 兼容接口）
- model 默认 `glm-4.6`（生产推荐）/ `glm-4-flash`（演示低成本）
- API key 通过 settings.glm_api_key 注入（已 .gitignore 防泄露）

参考:
- PRD §15.0 评分点 #5/7/8 → LLM-04/05/06
- STACK.md §4.6 GLM via OpenAI-compatible 代码样例
- PITFALLS #22 GLM 卡顿降级（调用方负责 asyncio.timeout，本模块只负责构造 client）
"""

from __future__ import annotations

from functools import lru_cache

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - openai dep 必须装，仅防御
    AsyncOpenAI = None  # type: ignore[assignment,misc]

from offboarding_flow.config import get_settings


@lru_cache(maxsize=1)
def build_glm_client() -> object:
    """构造 AsyncOpenAI client（lru_cache 单例，启动后冻结）。

    Returns:
        AsyncOpenAI 实例（用 object 类型注解避免 openai 未装时 import 错）。

    Raises:
        RuntimeError: openai 包未装时
    """
    if AsyncOpenAI is None:  # pragma: no cover
        raise RuntimeError("openai 包未安装 — 执行 `uv add 'openai>=1.40'` 后重试（STACK.md §4.6）")
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
    )


def reset_glm_client() -> None:
    """测试用 — 清缓存让下次 build 取新 settings。"""
    build_glm_client.cache_clear()
