import importlib.util
import sys
from pathlib import Path

import pytest


BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

MODULE_PATH = BENCHMARKS_DIR / "calibrate_thresholds.py"
spec = importlib.util.spec_from_file_location("calibrate_thresholds", MODULE_PATH)
calibration = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(calibration)


def _row(threshold, *, speed, similarity, reduction):
    return {
        "generative_threshold": threshold,
        "comparison": {
            "runtime_speedup": speed,
            "action_distribution_similarity": similarity,
            "expensive_request_or_turn_reduction_pct": reduction,
        },
    }


def test_parse_thresholds_deduplicates_preserving_order():
    assert calibration.parse_thresholds("0.68, 0.72, 0.68") == [0.68, 0.72]


def test_parse_thresholds_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        calibration.parse_thresholds("0.68,1.2")


def test_dominates_requires_no_metric_regression_and_one_improvement():
    stronger = _row(0.72, speed=1.5, similarity=0.7, reduction=80.0)
    weaker = _row(0.68, speed=1.2, similarity=0.6, reduction=60.0)
    tradeoff = _row(0.76, speed=1.8, similarity=0.5, reduction=90.0)

    assert calibration.dominates(stronger, weaker) is True
    assert calibration.dominates(stronger, tradeoff) is False


def test_pareto_frontier_removes_dominated_rows_but_keeps_tradeoffs():
    dominated = _row(0.68, speed=1.1, similarity=0.55, reduction=50.0)
    balanced = _row(0.72, speed=1.4, similarity=0.70, reduction=75.0)
    fast = _row(0.76, speed=1.8, similarity=0.58, reduction=90.0)

    frontier = calibration.pareto_frontier([dominated, fast, balanced])

    assert [row["generative_threshold"] for row in frontier] == [0.72, 0.76]
