from my_pi_eval.metrics import TaskMetric, calculate_summary


def test_calculate_summary():
    metrics = [
        TaskMetric(
            task_id="task-1",
            resolved=True,
            duration_sec=12.5,
            prompt_tokens=1000,
            completion_tokens=200,
            cache_read_tokens=500,
            cost_usd=0.005,
        ),
        TaskMetric(
            task_id="task-2",
            resolved=False,
            duration_sec=15.0,
            prompt_tokens=1500,
            completion_tokens=300,
            cache_read_tokens=600,
            cost_usd=0.007,
        ),
    ]
    summary = calculate_summary(metrics)
    assert summary["total_tasks"] == 2
    assert summary["resolved_tasks"] == 1
    assert summary["resolve_rate"] == 0.5
    assert summary["total_tokens"] == 3000  # prompt + completion
    assert summary["total_prompt_tokens"] == 2500
    assert summary["total_completion_tokens"] == 500
    assert summary["total_cache_read_tokens"] == 1100
    assert summary["total_duration_sec"] == 27.5
    assert round(summary["total_cost_usd"], 4) == 0.0120


def test_calculate_summary_empty():
    summary = calculate_summary([])
    assert summary["total_tasks"] == 0
    assert summary["resolved_tasks"] == 0
    assert summary["resolve_rate"] == 0.0
    assert summary["total_tokens"] == 0
