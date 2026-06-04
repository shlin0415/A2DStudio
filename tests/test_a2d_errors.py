"""Tests for A2D error classification and retry configuration."""
import asyncio

import httpx
import pytest

from ling_chat.core.a2d_errors import (
    ErrorType,
    RETRY_CONFIG,
    classify_exception,
    format_error_payload,
)


class TestClassifyException:
    def test_classify_timeout(self):
        e = asyncio.TimeoutError("timed out")
        assert classify_exception(e) == ErrorType.LLM_TIMEOUT

    def test_classify_llm_429(self):
        response = httpx.Response(429)
        e = httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("POST", "http://test"),
            response=response,
        )
        assert classify_exception(e) == ErrorType.LLM_API_ERROR

    def test_classify_llm_500(self):
        response = httpx.Response(500)
        e = httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("POST", "http://test"),
            response=response,
        )
        assert classify_exception(e) == ErrorType.LLM_API_ERROR

    def test_classify_network(self):
        e = httpx.ConnectError("connection refused")
        assert classify_exception(e) == ErrorType.NETWORK_ERROR

    def test_classify_network_timeout(self):
        e = httpx.ConnectTimeout("connect timeout")
        assert classify_exception(e) == ErrorType.NETWORK_ERROR

    def test_classify_format_error(self):
        e = ValueError("failed to parse LLM response")
        assert classify_exception(e) == ErrorType.FORMAT_ERROR

    def test_classify_tts_error(self):
        e = RuntimeError("GSV synthesis failed")
        assert classify_exception(e) == ErrorType.TTS_ERROR

    def test_classify_unknown(self):
        e = Exception("something weird")
        assert classify_exception(e) == ErrorType.UNKNOWN


class TestRetryConfig:
    def test_all_error_types_have_config(self):
        for attr in dir(ErrorType):
            if not attr.startswith("_"):
                error_type = getattr(ErrorType, attr)
                assert error_type in RETRY_CONFIG, (
                    f"{error_type} missing from RETRY_CONFIG"
                )

    def test_llm_timeout_retries_3(self):
        assert RETRY_CONFIG[ErrorType.LLM_TIMEOUT]["max_retries"] == 3

    def test_format_error_no_retry(self):
        assert RETRY_CONFIG[ErrorType.FORMAT_ERROR]["max_retries"] == 0

    def test_tts_error_retry_once(self):
        assert RETRY_CONFIG[ErrorType.TTS_ERROR]["max_retries"] == 1


class TestFormatErrorPayload:
    def test_includes_all_fields(self):
        e = RuntimeError("test error")
        payload = format_error_payload(ErrorType.UNKNOWN, e, "gen_123", 1)

        assert payload["error_type"] == ErrorType.UNKNOWN
        assert payload["message"] == "test error"
        assert "RuntimeError" in payload["detail"]
        assert payload["generation_id"] == "gen_123"
        assert payload["retry_count"] == 1
        assert payload["max_retries"] > 0

    def test_empty_generation_id(self):
        e = Exception("no gen")
        payload = format_error_payload(ErrorType.LLM_TIMEOUT, e, "", 0)

        assert payload["generation_id"] == ""
        assert payload["retry_count"] == 0
