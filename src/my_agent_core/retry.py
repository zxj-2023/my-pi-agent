"""LLM 自动重试策略与瞬时异常智能分类器（严格对齐 Pi / Tau 架构设计）。

提供指数退避（Exponential Backoff with Jitter）、瞬时抖动（429 / 5xx / 传输层断流）识别，
以及对致命凭证/权限错误（401 / 403 / 400）的即时熔断保护（Fail-Fast）。
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Any

# 瞬时可恢复模式正则（对齐 Pi 原厂 RETRYABLE_PROVIDER_ERROR_PATTERN）
_RETRYABLE_REGEX = re.compile(
    r"overloaded|currently experiencing high demand|rate.?limit|too many requests|"
    r"429|500|502|503|504|520|524|service.?unavailable|server.?error|internal.?error|"
    r"provider.?returned.?error|exceeded request buffer limit|network.?error|connection.?error|"
    r"connection.?refused|connection.?lost|fetch failed|getaddrinfo|enotfound|eai_again|"
    r"timed?\s*out|timeout|reset before headers|socket hang up|peer closed connection",
    re.IGNORECASE,
)

# 致命不可重试模式正则（对齐 Pi 原厂 NON_RETRYABLE_PROVIDER_LIMIT_ERROR_PATTERN）
_NON_RETRYABLE_REGEX = re.compile(
    r"gousagelimiterror|freeusagelimiterror|monthly usage limit reached|"
    r"available balance|insufficient_quota|out of budget|quota exceeded|billing|"
    r"authentication fails|invalid api key|invalid_api_key|unauthorized|"
    r"permission denied|permission_denied|bad request|invalid request",
    re.IGNORECASE,
)


@dataclass(slots=True)
class AutoRetryPolicy:
    """Agent Loop 专职 LLM 请求自动重试配置。"""

    max_retries: int = 3
    base_delay_ms: float = 2000.0
    max_delay_ms: float = 30000.0
    jitter: float = 0.2

    def is_retryable(self, exc: Exception) -> bool:
        """判定异常是否属于可安全重试的瞬时抖动。"""
        return is_retryable_error(exc)

    def compute_delay_ms(self, attempt: int, retry_after: float | None = None) -> float:
        """计算指定重试轮次的延迟毫秒数（支持服务端 Retry-After 头及带抖动的指数退避）。"""
        if retry_after is not None and retry_after > 0:
            try:
                return float(retry_after * 1000.0)
            except Exception:
                return 0.0

        # 指数退避: base * 2^(attempt - 1)
        factor = 2 ** max(0, attempt - 1)
        nominal_delay = self.base_delay_ms * factor

        # 增加抖动 (Jitter: +- self.jitter)
        if self.jitter > 0:
            jitter_delta = nominal_delay * self.jitter
            delay = nominal_delay + random.uniform(-jitter_delta, jitter_delta)
        else:
            delay = nominal_delay

        clamped = delay
        if clamped < 0.0:
            clamped = 0.0
        elif clamped > self.max_delay_ms:
            clamped = self.max_delay_ms
        try:
            return float(clamped)
        except Exception:
            return 0.0


def is_retryable_error(exc: Exception) -> bool:
    """全局无状态瞬时异常判定函数。"""
    err_str = str(exc)

    # 1. 优先排除非瞬时致命配额、计费或认证权限错误
    if _NON_RETRYABLE_REGEX.search(err_str):
        return False

    # 2. 检查 HTTP Status Code
    raw_status = getattr(exc, "status_code", None)
    if isinstance(raw_status, int):
        status_code: int | None = raw_status
    else:
        resp = getattr(exc, "response", None)
        resp_status = getattr(resp, "status_code", None)
        status_code = resp_status if isinstance(resp_status, int) else None

    if status_code is not None:
        if status_code in {400, 401, 403, 404, 422}:
            return False
        if status_code == 429:
            return True
        if status_code >= 500:
            return True

    # 3. 检查传输层与网络断流异常类型
    exc_type_name = type(exc).__name__
    if any(
        k in exc_type_name
        for k in (
            "ConnectError",
            "ConnectTimeout",
            "ReadTimeout",
            "PoolTimeout",
            "RemoteProtocolError",
            "ConnectionResetError",
            "BrokenPipeError",
            "APIConnectionError",
            "RateLimitError",
            "InternalServerError",
        )
    ):
        return True

    # 4. 正则匹配错误文本
    return bool(_RETRYABLE_REGEX.search(err_str))


def extract_retry_after(exc: Exception) -> float | None:
    """尝试从异常携带的响应头中提取 Retry-After（支持秒或毫秒）。"""
    response: Any = getattr(exc, "response", None)
    if response is None:
        return None

    headers: Any = getattr(response, "headers", None)
    if not headers or not hasattr(headers, "get"):
        return None

    # 检查标准 retry-after-ms 或 retry-after
    val_ms = headers.get("retry-after-ms")
    if val_ms:
        try:
            return float(val_ms) / 1000.0
        except (ValueError, TypeError):
            pass

    val_sec = headers.get("retry-after")
    if val_sec:
        try:
            return float(val_sec)
        except (ValueError, TypeError):
            pass

    return None
