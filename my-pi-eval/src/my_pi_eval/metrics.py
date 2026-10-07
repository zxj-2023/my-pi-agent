"""Evaluation metrics calculation and trajectory reporting."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class TaskMetric(BaseModel):
    """Metric data for a single benchmark task run."""

    task_id: str
    resolved: bool = False
    duration_sec: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    turns: int = 0
    error: str | None = None


def calculate_summary(metrics: list[TaskMetric]) -> dict[str, Any]:
    """Calculate aggregated benchmark summary across multiple tasks."""
    total_tasks = len(metrics)
    if total_tasks == 0:
        return {
            "total_tasks": 0,
            "resolved_tasks": 0,
            "resolve_rate": 0.0,
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_duration_sec": 0.0,
            "total_cost_usd": 0.0,
        }

    resolved_tasks = sum(1 for m in metrics if m.resolved)
    resolve_rate = resolved_tasks / total_tasks
    total_prompt = sum(m.prompt_tokens for m in metrics)
    total_completion = sum(m.completion_tokens for m in metrics)
    total_cache_read = sum(m.cache_read_tokens for m in metrics)
    total_duration = sum(m.duration_sec for m in metrics)
    total_cost = sum(m.cost_usd for m in metrics)

    return {
        "total_tasks": total_tasks,
        "resolved_tasks": resolved_tasks,
        "resolve_rate": resolve_rate,
        "total_tokens": total_prompt + total_completion,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_cache_read_tokens": total_cache_read,
        "total_duration_sec": total_duration,
        "total_cost_usd": total_cost,
    }
