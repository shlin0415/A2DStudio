"""A2D error classification and retry configuration."""


class ErrorType:
    LLM_TIMEOUT = "llm_timeout"
    LLM_API_ERROR = "llm_api_error"
    FORMAT_ERROR = "format_error"
    TTS_ERROR = "tts_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


RETRY_CONFIG = {
    ErrorType.LLM_TIMEOUT: {"max_retries": 3, "backoff": [5, 15, 30]},
    ErrorType.LLM_API_ERROR: {"max_retries": 3, "backoff": [5, 15, 30]},
    ErrorType.FORMAT_ERROR: {"max_retries": 0, "backoff": []},
    ErrorType.TTS_ERROR: {"max_retries": 1, "backoff": [3]},
    ErrorType.NETWORK_ERROR: {"max_retries": 3, "backoff": [2, 4, 8]},
    ErrorType.UNKNOWN: {"max_retries": 3, "backoff": [5, 15, 30]},
}


def classify_exception(e: Exception) -> str:
    """Classify an exception into an ErrorType string."""
    import asyncio

    type_name = type(e).__name__
    module_name = type(e).__module__ or ""

    # Timeout
    if isinstance(e, asyncio.TimeoutError):
        return ErrorType.LLM_TIMEOUT

    # httpx errors
    if "httpx" in module_name:
        if "ConnectError" in type_name or "ConnectTimeout" in type_name:
            return ErrorType.NETWORK_ERROR
        if "HTTPStatusError" in type_name:
            status = getattr(e, "response", None)
            if status is not None and hasattr(status, "status_code"):
                code = status.status_code
                if code == 429:
                    return ErrorType.LLM_API_ERROR
                if code >= 500:
                    return ErrorType.LLM_API_ERROR
            return ErrorType.LLM_API_ERROR
        if "Connect" in type_name:
            return ErrorType.NETWORK_ERROR
        return ErrorType.NETWORK_ERROR

    # aiohttp / requests network errors
    if any(x in type_name.lower() for x in ["connecterror", "connectionerror"]):
        return ErrorType.NETWORK_ERROR

    # Format / parse errors
    msg = str(e).lower()
    if any(kw in msg for kw in ["parse", "format", "invalid json", "malformed"]):
        return ErrorType.FORMAT_ERROR

    # TTS errors
    if any(kw in msg for kw in ["gsv", "tts", "synthesis"]):
        return ErrorType.TTS_ERROR

    # ValueError with parse/format context
    if isinstance(e, ValueError) and ("parse" in msg or "format" in msg):
        return ErrorType.FORMAT_ERROR

    return ErrorType.UNKNOWN


def format_error_payload(
    error_type: str,
    exception: Exception,
    generation_id: str,
    retry_count: int,
) -> dict:
    """Build the WS error payload dict."""
    import traceback
    from io import StringIO

    # Use format_exception to get the traceback even outside except blocks
    detail = "".join(
        traceback.format_exception(type(exception), exception, exception.__traceback__)
    )
    if not detail.strip():
        detail = f"{type(exception).__name__}: {exception}"

    config = RETRY_CONFIG.get(error_type, RETRY_CONFIG[ErrorType.UNKNOWN])
    return {
        "error_type": error_type,
        "message": str(exception),
        "detail": detail,
        "generation_id": generation_id,
        "retry_count": retry_count,
        "max_retries": config["max_retries"],
    }
