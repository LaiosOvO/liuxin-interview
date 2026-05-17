"""Provider Registry 配置化重构单测（Phase 8 收尾抽象）。

覆盖：
- 6 个内置 provider name 全部可见
- register_*_provider 加新名 → 可立即拿到
- 错误格式（缺 ':'）报 ValueError
- 未知 name 报错时打印可用清单
- _instantiate 按构造签名自动选择无参 / settings 注入
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from offboarding_flow.providers.factory import (
    available_doc_providers,
    available_im_providers,
    register_doc_provider,
    register_im_provider,
    reset_providers,
)


@pytest.fixture(autouse=True)
def _reset():
    """每个测试前后重置 registry 到内置默认（隔离）。"""
    yield
    reset_providers()


def test_builtin_doc_providers_listed():
    names = available_doc_providers()
    assert {"outline", "lark", "wecom", "dingtalk", "huly"}.issubset(set(names))


def test_builtin_im_providers_listed():
    names = available_im_providers()
    assert {"mattermost", "lark", "wecom", "dingtalk", "huly"}.issubset(set(names))


def test_register_doc_provider_adds_new_name():
    register_doc_provider("custom_slack", "my_pkg.slack:SlackDocs")
    assert "custom_slack" in available_doc_providers()


def test_register_im_provider_adds_new_name():
    register_im_provider("custom_telegram", "my_pkg.tg:TgIM")
    assert "custom_telegram" in available_im_providers()


def test_register_doc_provider_normalizes_case():
    register_doc_provider("  MyDocs  ", "my_pkg.docs:Docs")
    assert "mydocs" in available_doc_providers()
    assert "MyDocs" not in available_doc_providers()


def test_register_rejects_invalid_dotted_path():
    with pytest.raises(ValueError, match="module.path:Class"):
        register_doc_provider("bad", "no_colon_path")


def test_register_rejects_empty_name():
    with pytest.raises(ValueError, match="不能为空"):
        register_im_provider("   ", "my:X")


def test_unknown_provider_error_lists_available_names():
    """错误信息含 available 清单 + 建议 register API。"""
    from offboarding_flow.providers.factory import get_doc_provider

    with patch("offboarding_flow.providers.factory.get_settings") as mock_s:
        mock_s.return_value.doc_provider = "nonexistent_xyz"
        with pytest.raises(ValueError) as exc:
            get_doc_provider()
        msg = str(exc.value)
        assert "nonexistent_xyz" in msg
        assert "outline" in msg  # 列出可用
        assert "register_doc_provider" in msg  # 提示注册 API


def test_reset_clears_custom_registrations():
    register_im_provider("temp_test", "x:Y")
    assert "temp_test" in available_im_providers()
    reset_providers()
    assert "temp_test" not in available_im_providers()
    # 但内置 5 个仍在
    assert "mattermost" in available_im_providers()
    assert "huly" in available_im_providers()


def test_instantiate_no_args_class():
    """构造签名无非-self 参数 → 调 Class()。"""
    from offboarding_flow.providers.factory import _instantiate

    register_doc_provider("fake_no_args", "tests.unit.providers.test_factory_registry:_FakeNoArgs")
    obj = _instantiate("tests.unit.providers.test_factory_registry:_FakeNoArgs")
    assert isinstance(obj, _FakeNoArgs)
    assert obj.kind == "no_args"


def test_instantiate_settings_inject_class():
    """构造签名有 1 个非-self 参数 → 调 Class(settings)。"""
    from offboarding_flow.providers.factory import _instantiate

    obj = _instantiate("tests.unit.providers.test_factory_registry:_FakeWithSettings")
    assert isinstance(obj, _FakeWithSettings)
    # settings 实际是 get_settings() 返回的 Settings 实例
    assert obj.settings is not None


def test_instantiate_rejects_non_class():
    from offboarding_flow.providers.factory import _instantiate

    with pytest.raises(TypeError, match="不是类"):
        _instantiate("tests.unit.providers.test_factory_registry:_not_a_class")


def test_instantiate_rejects_unknown_module():
    from offboarding_flow.providers.factory import _instantiate

    with pytest.raises(ImportError, match="无法 import"):
        _instantiate("no.such.module:Foo")


def test_instantiate_rejects_unknown_attr():
    from offboarding_flow.providers.factory import _instantiate

    with pytest.raises(AttributeError, match="没有名为"):
        _instantiate("tests.unit.providers.test_factory_registry:NoSuchClass")


# 测试辅助类（不是真 Provider，仅验证 _instantiate 反射）
class _FakeNoArgs:
    def __init__(self):
        self.kind = "no_args"


class _FakeWithSettings:
    def __init__(self, settings):
        self.settings = settings


_not_a_class = "这不是类，是个字符串常量"
