# ruff: noqa: S105, S106
from unittest.mock import MagicMock, patch

import httpx
from my_agent_llm.auth.quota import (  # pyright: ignore[reportMissingImports]
    QuotaBucket,
    retrieve_user_quota_summary,
)

from my_agent_llm.auth.antigravity import (  # pyright: ignore[reportMissingImports]
    ANTIGRAVITY_USER_AGENT,
    DEFAULT_ANTIGRAVITY_ENDPOINT,
    AntigravityCredentials,
)


def test_retrieve_user_quota_summary_parses_buckets():
    creds = AntigravityCredentials(access_token="ya29.test", project_id="aicode-consumers")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "groups": [
            {
                "displayName": "Weekly Limit",
                "buckets": [
                    {
                        "bucketId": "gemini-weekly",
                        "displayName": "Weekly Limit Remaining",
                        "remainingFraction": 0.85,
                        "resetTime": "2026-09-15T00:00:00Z",
                    }
                ],
            }
        ]
    }

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        buckets = retrieve_user_quota_summary(creds)
        assert len(buckets) == 1
        assert buckets[0].bucket_id == "gemini-weekly"
        assert buckets[0].display_name == "Weekly Limit Remaining"
        assert buckets[0].remaining_fraction == 0.85
        assert buckets[0].reset_time == "2026-09-15T00:00:00Z"
        assert buckets[0].remaining_percent == 85

        mock_post.assert_called_once_with(
            f"{DEFAULT_ANTIGRAVITY_ENDPOINT}/v1internal:retrieveUserQuotaSummary",
            headers={
                "Authorization": "Bearer ya29.test",
                "x-goog-user-project": "aicode-consumers",
                "User-Agent": ANTIGRAVITY_USER_AGENT,
                "Content-Type": "application/json",
            },
            json={},
            timeout=10.0,
        )


def test_retrieve_user_quota_summary_multiple_groups_and_buckets():
    creds = AntigravityCredentials(access_token="token_123", project_id="custom-project")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "groups": [
            {
                "displayName": "Group 1",
                "buckets": [
                    {
                        "bucketId": "bucket-1",
                        "displayName": "Bucket 1",
                        "remainingFraction": 0.5,
                    },
                    {
                        "bucketId": "bucket-2",
                        "displayName": "Bucket 2",
                        "remainingFraction": 1.0,
                        "resetTime": "2026-09-20T00:00:00Z",
                    },
                ],
            },
            {
                "displayName": "Group 2",
                "buckets": [
                    {
                        "bucketId": "bucket-3",
                        "displayName": "Bucket 3",
                        "remainingFraction": 0.0,
                    }
                ],
            },
        ]
    }

    with patch("httpx.post", return_value=mock_resp):
        buckets = retrieve_user_quota_summary(creds)
        assert len(buckets) == 3
        assert [b.bucket_id for b in buckets] == ["bucket-1", "bucket-2", "bucket-3"]
        assert [b.remaining_percent for b in buckets] == [50, 100, 0]


def test_retrieve_user_quota_summary_http_error():
    creds = AntigravityCredentials(access_token="ya29.test", project_id="aicode-consumers")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("httpx.post", return_value=mock_resp):
        buckets = retrieve_user_quota_summary(creds)
        assert buckets == []


def test_retrieve_user_quota_summary_network_exception():
    creds = AntigravityCredentials(access_token="ya29.test", project_id="aicode-consumers")

    with patch("httpx.post", side_effect=httpx.ConnectTimeout("Connection timed out")):
        buckets = retrieve_user_quota_summary(creds)
        assert buckets == []


def test_quota_bucket_remaining_percent_clamping():
    b_high = QuotaBucket(bucket_id="b1", display_name="B1", remaining_fraction=1.5)
    assert b_high.remaining_percent == 100

    b_low = QuotaBucket(bucket_id="b2", display_name="B2", remaining_fraction=-0.2)
    assert b_low.remaining_percent == 0

    b_round = QuotaBucket(bucket_id="b3", display_name="B3", remaining_fraction=0.666)
    assert b_round.remaining_percent == 67
