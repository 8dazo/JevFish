#!/usr/bin/env python3
"""Sweep JevFish generative thresholds against one shared LLM baseline.

The sweep keeps the cheap-action threshold fixed and varies only the confidence
required for language-heavy actions. It reports the non-dominated (Pareto)
configurations across runtime speedup, behavioral-distribution similarity, and
expensive-model request reduction.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from jevfish_ab import compare, require_env, run_arm


def parse_thresholds(raw: str) -> list[float]:
    values: list[float] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = float(item)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"threshold out of range: {value}")
        if value not in values:
            values.append(value)
    if not values:
        raise ValueError("at least one generative threshold is required")
    return values


def _metric(row: dict[str, Any], key: str) -> float:
    value = row["comparison"].get(key)
    return float(value) if value is not None else float("-inf")


def dominates(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = (
        "runtime_speedup",
        "action_distribution_similarity",
        "expensive_request_or_turn_reduction_pct",
    )
    a_values = [_metric(a, key) for key in keys]
    b_values = [_metric(b, key) for key in keys]
    return all(x >= y for x, y in zip(a_values, b_values)) and any(
        x > y for x, y in zip(a_values, b_values)
    )


def pareto_frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frontier = []
    for candidate in rows:
        if any(
            dominates(other, candidate)
            for other in rows
            if other is not candidate
        ):
            continue
        frontier.append(candidate)
    return sorted(frontier, key=lambda row: row["generative_threshold"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--base-threshold", type=float, default=0.58)
    parser.add_argument(
        "--generative-thresholds",
        default="0.68,0.72,0.76",
        help="Comma-separated confidence thresholds for quote/comment/create-post",
    )
    parser.add_argument("--max-actions", type=int, default=3)
    parser.add_argument("--output", default="jevfish-calibration-report.json")
    args = parser.parse_args()

    if args.agents < 2:
        raise SystemExit("--agents must be >= 2")
    if args.rounds < 1:
        raise SystemExit("--rounds must be >= 1")

    thresholds = parse_thresholds(args.generative_thresholds)
    require_env("TYPESAFE_API_KEY")
    require_env("LLM_API_KEY")
    require_env("LLM_MODEL_NAME")

    report: dict[str, Any] = {
        "config": {
            "agents": args.agents,
            "rounds": args.rounds,
            "base_threshold": args.base_threshold,
            "generative_thresholds": thresholds,
            "max_actions": args.max_actions,
            "jev_model": os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest"),
            "llm_model": os.environ.get("LLM_MODEL_NAME"),
        },
        "note": (
            "The same LLM-only baseline is reused for every hybrid threshold. "
            "Pareto membership is descriptive for this simulation setup; it is "
            "not a claim of real-world predictive accuracy."
        ),
    }

    try:
        baseline = run_arm(
            "llm",
            agents=args.agents,
            rounds=args.rounds,
            threshold=args.base_threshold,
            max_actions=args.max_actions,
        )
        report["llm_baseline"] = baseline

        rows: list[dict[str, Any]] = []
        for threshold in thresholds:
            os.environ["JEVFISH_GENERATIVE_CONFIDENCE_THRESHOLD"] = str(threshold)
            os.environ["JEVFISH_TARGET_CONFIDENCE_THRESHOLD"] = str(
                args.base_threshold
            )
            hybrid = run_arm(
                "hybrid",
                agents=args.agents,
                rounds=args.rounds,
                threshold=args.base_threshold,
                max_actions=args.max_actions,
            )
            rows.append(
                {
                    "generative_threshold": threshold,
                    "hybrid": hybrid,
                    "comparison": compare(
                        hybrid,
                        baseline,
                        agents=args.agents,
                        rounds=args.rounds,
                    ),
                }
            )

        report["runs"] = rows
        frontier = pareto_frontier(rows)
        report["pareto_thresholds"] = [
            row["generative_threshold"] for row in frontier
        ]
        report["pareto_frontier"] = [
            {
                "generative_threshold": row["generative_threshold"],
                "runtime_speedup": row["comparison"].get("runtime_speedup"),
                "action_distribution_similarity": row["comparison"].get(
                    "action_distribution_similarity"
                ),
                "expensive_request_or_turn_reduction_pct": row["comparison"].get(
                    "expensive_request_or_turn_reduction_pct"
                ),
            }
            for row in frontier
        ]
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


if __name__ == "__main__":
    main()
