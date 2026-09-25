# pyright: reportMissingImports=false
import httpx

from my_agent_core.retry import AutoRetryPolicy, is_retryable_error


def test_is_retryable_transient_http_status_codes():
    policy = AutoRetryPolicy()

    # 429 RateLimit
    class Dummy429(Exception):
        status_code = 429

    assert policy.is_retryable(Dummy429("Rate limit exceeded"))
    assert is_retryable_error(Dummy429("Rate limit exceeded"))

    # 5xx Server Errors
    for code in [500, 502, 503, 504]:

        class Dummy5xx(Exception):
            status_code = code

        assert policy.is_retryable(Dummy5xx(f"Server error {code}"))


def test_is_retryable_transport_network_errors():
    policy = AutoRetryPolicy()

    assert policy.is_retryable(httpx.ConnectError("Connection refused"))
    assert policy.is_retryable(httpx.ConnectTimeout("Connect timed out"))
    assert policy.is_retryable(httpx.ReadTimeout("Read timed out"))
    assert policy.is_retryable(httpx.RemoteProtocolError("Connection closed unexpectedly"))
    assert policy.is_retryable(ConnectionResetError("Connection reset by peer"))


def test_is_retryable_error_message_regex():
    policy = AutoRetryPolicy()

    assert policy.is_retryable(RuntimeError("overloaded: system under heavy demand"))
    assert policy.is_retryable(RuntimeError("Error code 503: Service Unavailable"))
    assert policy.is_retryable(RuntimeError("fetch failed: socket hang up"))


def test_fatal_errors_fail_fast_without_retry():
    policy = AutoRetryPolicy()

    # 401 Auth error
    class Dummy401(Exception):
        status_code = 401

    assert not policy.is_retryable(Dummy401("Authentication Fails, Your api key is invalid"))

    # 403 Forbidden
    class Dummy403(Exception):
        status_code = 403

    assert not policy.is_retryable(Dummy403("Forbidden"))

    # 400 Bad Request
    class Dummy400(Exception):
        status_code = 400

    assert not policy.is_retryable(Dummy400("Bad Request"))

    # 429 with insufficient quota (non-retryable account limit)
    class DummyQuota(Exception):
        status_code = 429

    assert not policy.is_retryable(DummyQuota("insufficient_quota: billing limit reached"))
    assert not policy.is_retryable(RuntimeError("out of budget: please recharge"))


def test_compute_delay_exponential_backoff_and_jitter():
    policy = AutoRetryPolicy(base_delay_ms=1000, max_delay_ms=10000, jitter=0.2)

    # Attempt 1: base ~ 1000ms +- 20%
    d1 = policy.compute_delay_ms(attempt=1)
    assert 800 <= d1 <= 1200

    # Attempt 2: base ~ 2000ms +- 20%
    d2 = policy.compute_delay_ms(attempt=2)
    assert 1600 <= d2 <= 2400

    # Explicit retry-after header
    d_explicit = policy.compute_delay_ms(attempt=1, retry_after=5.0)
    assert d_explicit == 5000.0
