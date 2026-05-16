"""单元测试：workers.evidence_missing_detector（TIMEOUT-02 / 评分点 #6）。"""

from __future__ import annotations

import pytest

from offboarding_flow.workers.evidence_missing_detector import (
    EVIDENCE_MIN_LENGTH,
    detect_evidence_missing,
    is_text_evidence_missing,
)


class TestIsTextEvidenceMissing:
    def test_none_is_missing(self):
        assert is_text_evidence_missing(None) is True

    def test_empty_is_missing(self):
        assert is_text_evidence_missing("") is True

    def test_whitespace_only_is_missing(self):
        assert is_text_evidence_missing("   \t\n  ") is True

    def test_too_short_is_missing(self):
        assert is_text_evidence_missing("ok") is True
        assert is_text_evidence_missing("完成") is True  # 2 字符

    @pytest.mark.parametrize("text", ["完好归还ok", "OK ok ok", "已签字确认"])
    def test_sufficient_text_is_not_missing(self, text: str):
        assert is_text_evidence_missing(text) is False

    def test_exactly_min_length_is_not_missing(self):
        # EVIDENCE_MIN_LENGTH = 5
        text = "a" * EVIDENCE_MIN_LENGTH
        assert is_text_evidence_missing(text) is False


class TestDetectEvidenceMissing:
    def test_dict_with_explicit_flag_true(self):
        node = {"result_text": "已归还笔记本", "evidence_missing": True}
        assert detect_evidence_missing(node) is True  # 显式优先

    def test_dict_with_short_text(self):
        node = {"result_text": "ok", "evidence_missing": False}
        assert detect_evidence_missing(node) is True

    def test_dict_with_sufficient_text(self):
        node = {"result_text": "已归还所有设备并签字确认", "evidence_missing": False}
        assert detect_evidence_missing(node) is False

    def test_dict_missing_evidence_missing_key(self):
        node = {"result_text": "已确认"}  # 3 字符
        assert detect_evidence_missing(node) is True  # 短文本兜底

    def test_orm_like_object_with_attributes(self):
        class FakeNode:
            result_text = "已归还笔记本 MacBook Pro"
            evidence_missing = False

        assert detect_evidence_missing(FakeNode()) is False

    def test_orm_like_explicit_flag(self):
        class FakeNode:
            result_text = "已归还笔记本 MacBook Pro"
            evidence_missing = True  # 显式标记证据缺失

        assert detect_evidence_missing(FakeNode()) is True
