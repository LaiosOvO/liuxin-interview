"""协作文档 + IM 平台 Provider 抽象。

支持 Outline / Lark(飞书) / WeCom(企微) / DingTalk(钉钉)。
通过 DOC_PROVIDER / IM_PROVIDER env 切换实现。
"""

from .base import (
    CollectionInfo,
    DispatchFn,
    DocInfo,
    DocProvider,
    IMProvider,
    ProviderError,
    UserInfo,
)
from .factory import get_doc_provider, get_im_provider, reset_providers

__all__ = [
    "CollectionInfo",
    "DispatchFn",
    "DocInfo",
    "DocProvider",
    "IMProvider",
    "ProviderError",
    "UserInfo",
    "get_doc_provider",
    "get_im_provider",
    "reset_providers",
]
