from __future__ import annotations

from dataclasses import dataclass

import httpx

from .antigravity import (
    ANTIGRAVITY_USER_AGENT,
    DEFAULT_ANTIGRAVITY_ENDPOINT,
    AntigravityCredentials,
)


@dataclass
class QuotaBucket:
    """单个模型或操作类型的配额桶。"""

    bucket_id: str
    display_name: str
    remaining_fraction: float
    reset_time: str | None = None

    @property
    def remaining_percent(self) -> int:
        """配额剩余百分比（0-100 整数）。"""
        return int(round(max(0.0, min(1.0, self.remaining_fraction)) * 100))


def retrieve_user_quota_summary(creds: AntigravityCredentials) -> list[QuotaBucket]:
    """向 Google Cloud Code 网关查询当前用户各模型配额余量。"""
    url = f"{DEFAULT_ANTIGRAVITY_ENDPOINT}/v1internal:retrieveUserQuotaSummary"
    headers = {
        "Authorization": f"Bearer {creds.access_token}",
        "x-goog-user-project": creds.project_id,
        "User-Agent": ANTIGRAVITY_USER_AGENT,
        "Content-Type": "application/json",
    }
    try:
        res = httpx.post(url, headers=headers, json={}, timeout=10.0)
        if res.status_code != 200:
            return []
        data = res.json()
        buckets: list[QuotaBucket] = []
        for group in data.get("groups", []):
            for b in group.get("buckets", []):
                buckets.append(
                    QuotaBucket(
                        bucket_id=b.get("bucketId", ""),
                        display_name=b.get("displayName", ""),
                        remaining_fraction=float(b.get("remainingFraction", 0.0)),
                        reset_time=b.get("resetTime"),
                    )
                )
        return buckets
    except Exception:
        return []
