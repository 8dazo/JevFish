#!/usr/bin/env python3
"""Run paired repeated JevFish hybrid-vs-LLM trials.

Each trial gives the hybrid and baseline arms the same local/OASIS seed. Trial
order alternates to reduce systematic provider/time-order bias. Remote model
providers can remain nondeterministic, so the report summarizes distributions
rather than treating the seed as exact end-to-end determinism.

A trial is only accepted as benchmark evidence when the hybrid arm consumes the
personalized OASIS recommendation feed without observation fallback and the LLM
arm remains the untouched upstream baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path
from typing import Any

from jevfish_ab import compare, require_env, run_arm


def _numeric(values: list[Any]) -> list[float]:
    return [float(value) for value in values if value is not None]


def summarize(values: list[Any]) -> dict[str, float | int | None]:
    numbers = _numeric(values)
    if not numbers:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "stdev": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(numbers),
        "mean": round(statistics.fmean(numbers), 4),
        "median": round(statistics.median(numbers), 4),
        "stdev": round(statistics.stdev(numbers), 4) if len(numbers) > 1 else 0.0,
        "min": round(min(numbers), 4),
        "max": round(max(numbers), 4),
    }


def aggregate(trials: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons = [trial["comparison"] for trial in trials]
    return {
        "runtime_speedup": summarize(
            [row.get("runtime_speedup") for row in comparisons]
        ),
        "action_distribution_similarity": summarize(
            [row.get("action_distribution_similarity") for row in comparisons]
        ),
        "expensive_request_or_turn_reduction_pct": summarize(
            [row.get("expensive_request_or_turn_reduction_pct") for row in comparisons]
        ),
        "hybrid_loop_seconds": summarize(
            [
                trial["hybrid"].get("loop_seconds")
                or trial["hybrid"].get("elapsed_seconds")
                for trial in trials
            ]
        ),
        "llm_loop_seconds": summarize(
            [
                trial["llm"].get("loop_seconds")
                or trial["llm"].get("elapsed_seconds")
                for trial in trials
            ]
        ),
        "hybrid_system_two_requests": summarize(
            [
                trial["hybrid"].get("metrics", {}).get("system_two_requests")
                for trial in trials
            ]
        ),
        "hybrid_full_llm_fallbacks": summarize(
            [
                trial["hybrid"].get("metrics", {}).get("llm_fallbacks")
                for trial in trials
            ]
        ),
        "hybrid_observation_posts": summarize(
            [
                trial["hybrid"].get("metrics", {}).get("observation_posts")
                for trial in trials
            ]
        ),
        "hybrid_observation_fallbacks": summarize(
            [
                trial["hybrid"].get("metrics", {}).get("observation_fallbacks")
                for trial in trials
            ]
        ),
        "hybrid_observation_errors": summarize(
            [
                trial["hybrid"].get("metrics", {}).get("observation_errors")
                for trial in trials
            ]
        ),
    }


def validate_trial(trial: dict[str, Any]) -> list[str]:
    """Return reasons a trial should not be used as benchmark evidence."""
    problems: list[str] = []
    hybrid_metrics = trial["hybrid"].get("metrics", {})
    llm_metrics = trial["llm"].get("metrics", {})

    if hybrid_metrics.get("observation_mode") != "oasis_refresh":
        problems.append("hybrid did not use oasis_refresh observations")
    if int(hybrid_metrics.get("observation_fallbacks") or 0) != 0:
        problems.append("hybrid observation fallback occurred")
    if int(hybrid_metrics.get("observation_errors") or 0) != 0:
        problems.append("hybrid observation error occurred")
    if int(hybrid_metrics.get("observation_posts") or 0) <= 0:
        problems.append("hybrid received no personalized observation posts")
    if llm_metrics.get("observation_mode") != "upstream_llm":
        problems.append("LLM arm is not the untouched upstream observation baseline")

    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threshold", type=float, default=0.58)
    parser.add_argument("--generative-threshold", type=float, default=0.72)
    parser.add_argument("--max-actions", type=int, default=3)
    parser.add_argument("--output", default="jevfish-repeated-trials.json")
    args = parser.parse_args()

    if args.agents < 2:
        raise SystemExit("--agents must be >= 2")
    if args.rounds < 1:
        raise SystemExit("--rounds must be >= 1")
    if args.trials < 2:
        raise SystemExit("--trials must be >= 2")

    require_env("TYPESAFE_API_KEY")
    require_env("LLM_API_KEY")
    require_env("LLM_MODEL_NAME")

    os.environ["JEVFISH_GENERATIVE_CONFIDENCE_THRESHOLD"] = str(
        args.generative_threshold
    )
    os.environ["JEVFISH_TARGET_CONFIDENCE_THRESHOLD"] = str(args.threshold)
    os.environ["JEVFISH_OBSERVATION_MODE"] = "oasis_refresh"

    report: dict[str, Any] = {
        "config": {
            "agents": args.agents,
            "rounds": args.rounds,
            "trials": args.trials,
            "base_seed": args.seed,
            "threshold": args.threshold,
            "generative_threshold": args.generative_threshold,
            "max_actions": args.max_actions,
            "jev_model": os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest"),
            "llm_model": os.environ.get("LLM_MODEL_NAME"),
            "observation_mode": "oasis_refresh",
        },
        "note": (
            "Seeds control local/OASIS stochasticity, not remote provider "
            "determinism. Aggregate metrics describe these simulation-policy "
            "trials and are not real-world predictive accuracy."
        ),
    }

    try:
        trials: list[dict[str, Any]] = []
        invalid_reasons: list[dict[str, Any]] = []
        for index in range(args.trials):
            seed = args.seed + index
            os.environ["JEVFISH_SEED"] = str(seed)
            os.environ["PYTHONHASHSEED"] = str(seed)

            # Alternate arm order to reduce systematic ordering/provider-load bias.
            order = ["hybrid", "llm"] if index % 2 == 0 else ["llm", "hybrid"]
            arms: dict[str, dict[str, Any]] = {}
            for mode in order:
                arms[mode] = run_arm(
                    mode,
                    agents=args.agents,
                    rounds=args.rounds,
                    threshold=args.threshold,
                    max_actions=args.max_actions,
                )

            trial = {
                "trial": index + 1,
                "seed": seed,
                "execution_order": order,
                "hybrid": arms["hybrid"],
                "llm": arms["llm"],
                "comparison": compare(
                    arms["hybrid"],
                    arms["llm"],
                    agents=args.agents,
                    rounds=args.rounds,
                ),
            }
            problems = validate_trial(trial)
            trial["benchmark_valid"] = not problems
            trial["validation_problems"] = problems
            if problems:
                invalid_reasons.append({"trial": index + 1, "problems": problems})
            trials.append(trial)

        report["trials"] = trials
        report["aggregate"] = aggregate(trials)
        report["benchmark_valid"] = not invalid_reasons
        report["invalid_trials"] = invalid_reasons
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        Path(args.output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise

    Path(args.output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not report["benchmark_valid"]:
        raise SystemExit("Repeated trials completed but failed benchmark validity checks")


if __name__ == "__main__":
    main()
