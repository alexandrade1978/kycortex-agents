from __future__ import annotations

from typing import Optional


_RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429}


def extract_http_status_code(exc: Exception) -> Optional[int]:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    status_code = getattr(exc, "code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

    return None


def is_retryable_http_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_HTTP_STATUS_CODES or 500 <= status_code <= 599


def is_transient_provider_exception(exc: Exception) -> bool:
    status_code = extract_http_status_code(exc)
    if status_code is None:
        return True
    return is_retryable_http_status(status_code)