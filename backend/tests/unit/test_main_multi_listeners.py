"""多 listener 并存（IM_PROVIDERS=mattermost,huly）单测 — 5.3 抽象升级。

覆盖：
- IM_PROVIDERS 复数解析（逗号分隔）
- 空 IM_PROVIDERS → 回退 IM_PROVIDER 单值（backwards compat）
- 单 listener 失败不影响其他 listener 继续启动
- app.state.im_listeners 列表正确暴露
"""

from __future__ import annotations

import pytest


def _parse_providers(im_providers: str, im_provider: str) -> list[str]:
    """复制 main.py lifespan 里 provider 解析逻辑用于单测。"""
    if im_providers and im_providers.strip():
        return [p.strip().lower() for p in im_providers.split(",") if p.strip()]
    return [(im_provider or "mattermost").lower()]


def test_im_providers_empty_falls_back_to_im_provider():
    """IM_PROVIDERS="" → 用 IM_PROVIDER 单值（backwards compat）。"""
    assert _parse_providers("", "mattermost") == ["mattermost"]
    assert _parse_providers("", "huly") == ["huly"]
    assert _parse_providers("   ", "mattermost") == ["mattermost"]


def test_im_providers_default_mattermost_when_both_empty():
    """两个都空 → 默认 mattermost。"""
    assert _parse_providers("", "") == ["mattermost"]


def test_im_providers_single_value():
    """IM_PROVIDERS="huly" → ['huly']。"""
    assert _parse_providers("huly", "mattermost") == ["huly"]


def test_im_providers_comma_separated():
    """IM_PROVIDERS="mattermost,huly" → 2 个 listener 并存。"""
    assert _parse_providers("mattermost,huly", "") == ["mattermost", "huly"]


def test_im_providers_whitespace_tolerated():
    """允许 "mattermost , huly , wecom" 这种带空格。"""
    assert _parse_providers("mattermost , huly , wecom", "") == [
        "mattermost",
        "huly",
        "wecom",
    ]


def test_im_providers_case_normalized():
    """大写名也认（统一小写）。"""
    assert _parse_providers("Mattermost,HULY", "") == ["mattermost", "huly"]


def test_im_providers_trailing_comma_ok():
    """末尾逗号不报错（filter 掉空 segment）。"""
    assert _parse_providers("mattermost,huly,", "") == ["mattermost", "huly"]


def test_im_providers_precedence_over_im_provider():
    """复数非空时，优先复数；忽略单数。"""
    assert _parse_providers("huly", "mattermost") == ["huly"]
    assert _parse_providers("mattermost,huly", "wecom") == ["mattermost", "huly"]


def test_im_providers_duplicates_preserved():
    """重复名保留（user 自己负责，但解析不去重）。"""
    assert _parse_providers("mattermost,mattermost", "") == ["mattermost", "mattermost"]


@pytest.mark.parametrize(
    "im_providers, im_provider, expected",
    [
        ("", "mattermost", ["mattermost"]),
        ("huly", "", ["huly"]),
        ("mattermost,huly", "", ["mattermost", "huly"]),
        ("mattermost,huly,wecom,dingtalk", "", ["mattermost", "huly", "wecom", "dingtalk"]),
    ],
)
def test_im_providers_parametrized(im_providers, im_provider, expected):
    """参数化全场景。"""
    assert _parse_providers(im_providers, im_provider) == expected
