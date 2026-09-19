import importlib.util
import sys
from pathlib import Path


BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

MODULE_PATH = BENCHMARKS_DIR / "repeated_trials.py"
spec = importlib.util.spec_from_file_location("repeated_trials", MODULE_PATH)
trials = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(trials)


def test_summarize_reports_distribution_not_single_value():
    result = trials.summarize([1.0, 2.0, 3.0])
    assert result["count"] == 3
    assert result["mean"] == 2.0
    assert result["median"] == 2.0
    assert result["stdev"] == 1.0
    assert result["min"] == 1.0
    assert result["max"] == 3.0


def test_aggregate_collects_policy_metrics():
    rows = [
        {
            "comparison": {
                "runtime_speedup": 1.5,
                "action_distribution_similarity": 0.6,
                "expensive_request_or_turn_reduction_pct": 80.0,
            },
            "hybrid": {
                "loop_seconds": 10.0,
                "metrics": {"system_two_requests": 1, "llm_fallbacks": 0},
            },
            "llm": {"loop_seconds": 15.0},
        },
        {
            "comparison": {
                "runtime_speedup": 2.0,
                "action_distribution_similarity": 0.7,
                "expensive_request_or_turn_reduction_pct": 60.0,
            },
            "hybrid": {
                "loop_seconds": 12.0,
                "metrics": {"system_two_requests": 2, "llm_fallbacks": 0},
            },
            "llm": {"loop_seconds": 24.0},
        },
    ]

    result = trials.aggregate(rows)

    assert result["runtime_speedup"]["median"] == 1.75
    assert result["action_distribution_similarity"]["mean"] == 0.65
    assert result["expensive_request_or_turn_reduction_pct"]["mean"] == 70.0
    assert result["hybrid_system_two_requests"]["mean"] == 1.5
    assert result["hybrid_full_llm_fallbacks"]["mean"] == 0.0
