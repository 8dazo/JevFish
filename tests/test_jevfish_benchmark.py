import importlib.util
from pathlib import Path


BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "jevfish_ab.py"
spec = importlib.util.spec_from_file_location("jevfish_ab", BENCHMARK_PATH)
benchmark = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(benchmark)


def test_adjusted_behavior_counts_removes_admin_and_seed_posts():
    adjusted = benchmark.adjusted_behavior_counts(
        {
            "sign_up": 5,
            "create_post": 5,
            "like_post": 7,
            "follow": 2,
        }
    )

    assert adjusted == {
        "create_post": 3,
        "like_post": 7,
        "follow": 2,
    }


def test_distribution_similarity_is_bounded_and_exact_for_same_distribution():
    assert benchmark.distribution_similarity(
        {"like_post": 3, "follow": 1},
        {"like_post": 6, "follow": 2},
    ) == 1.0

    score = benchmark.distribution_similarity(
        {"like_post": 4},
        {"follow": 4},
    )
    assert score == 0.0


def test_compare_counts_expensive_turns_and_speedup():
    hybrid = {
        "loop_seconds": 10.0,
        "elapsed_seconds": 12.0,
        "metrics": {
            "llm_fallbacks": 1,
            "system_two_calls": 2,
        },
        "database": {
            "trace_actions": {
                "sign_up": 5,
                "create_post": 3,
                "like_post": 5,
                "follow": 1,
            }
        },
    }
    llm = {
        "loop_seconds": 25.0,
        "elapsed_seconds": 28.0,
        "metrics": {"llm_fallbacks": 5},
        "database": {
            "trace_actions": {
                "sign_up": 5,
                "create_post": 4,
                "like_post": 6,
                "follow": 2,
            }
        },
    }

    result = benchmark.compare(hybrid, llm, agents=5, rounds=1)

    assert result["agent_rounds"] == 5
    assert result["hybrid_expensive_model_turns"] == 3
    assert result["baseline_llm_agent_turns"] == 5
    assert result["expensive_turns_avoided"] == 2
    assert result["expensive_turns_avoided_pct"] == 40.0
    assert result["runtime_speedup"] == 2.5
    assert 0.0 <= result["action_distribution_similarity"] <= 1.0
