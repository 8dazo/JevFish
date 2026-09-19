#!/usr/bin/env python3
"""Run a controlled JevFish hybrid-vs-LLM A/B experiment.

Both arms start from the same synthetic society and seed posts. The benchmark
uses the production OASIS Twitter entrypoint, persists each SQLite world, and
reports runtime, expensive model requests/turns, action distributions, and a
simple distribution-similarity score.

Important: these are simulation-model measurements, not probabilities about
the real world.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "backend" / "scripts" / "run_twitter_simulation.py"
SEED_POST_COUNT = 2

PERSONAS = [
    (
        "Asha",
        "Pragmatic systems engineer. Likes reproducible benchmarks, open-source "
        "infrastructure, and concrete claims; rarely posts without a reason.",
    ),
    (
        "Ben",
        "Skeptical performance researcher. Challenges vague claims and engages "
        "with careful experiments, methodology, and reproducibility.",
    ),
    (
        "Cara",
        "AI infrastructure researcher. Curious about fast decision models, "
        "multi-agent systems, evaluation, and scaling experiments.",
    ),
    (
        "Diego",
        "Open-source maintainer. Likes useful engineering work, shares practical "
        "releases, and tends to ignore hype.",
    ),
    (
        "Eva",
        "Developer-tools product engineer. Interested in user-visible speedups, "
        "clear UX, and thoughtful product experiments.",
    ),
    (
        "Farah",
        "Applied ML engineer. Enjoys implementation details and empirical "
        "trade-offs, but is cautious about claims without baselines.",
    ),
    (
        "Gabe",
        "Independent developer. Tries new tools early, reposts genuinely useful "
        "projects, and asks blunt questions about setup and cost.",
    ),
    (
        "Hana",
        "Research-minded product builder. Interested in social dynamics, "
        "simulation validity, and what metrics actually mean.",
    ),
]


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def make_people(count: int) -> list[dict[str, Any]]:
    people = []
    for agent_id in range(count):
        base_name, persona = PERSONAS[agent_id % len(PERSONAS)]
        name = f"{base_name} {agent_id + 1}"
        people.append(
            {
                "agent_id": agent_id,
                "name": name,
                "username": f"{base_name.lower()}_{agent_id + 1}",
                "persona": persona,
            }
        )
    return people


def write_profiles(path: Path, people: list[dict[str, Any]]) -> None:
    rows = []
    count = len(people)
    for person in people:
        aid = int(person["agent_id"])
        following = []
        if count > 1:
            following.append((aid + 1) % count)
        if count > 2:
            following.append((aid + 2) % count)
        rows.append(
            {
                "name": person["name"],
                "username": person["username"],
                "user_char": person["persona"],
                "description": person["persona"][:180],
                "following_agentid_list": json.dumps(following),
                "previous_tweets": "[]",
            }
        )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_config(
    path: Path,
    people: list[dict[str, Any]],
    *,
    rounds: int,
    mode: str,
) -> None:
    count = len(people)
    config = {
        "simulation_id": f"jevfish_ab_{mode}",
        "llm_model": os.environ.get(
            "LLM_MODEL_NAME", "meta/muse-spark-1.3-contributor"
        ),
        "agent_configs": [
            {
                "agent_id": person["agent_id"],
                "entity_name": person["name"],
                "bio": person["persona"],
                "activity_level": 1.0,
                "active_hours": list(range(24)),
            }
            for person in people
        ],
        "time_config": {
            "total_simulation_hours": rounds,
            "minutes_per_round": 60,
            "agents_per_hour_min": count,
            "agents_per_hour_max": count,
            "peak_hours": [],
            "off_peak_hours": [],
            "peak_activity_multiplier": 1.0,
            "off_peak_activity_multiplier": 1.0,
        },
        "event_config": {
            "initial_posts": [
                {
                    "poster_agent_id": 0,
                    "content": (
                        "We replaced many small generative-agent decisions with "
                        "a fast probabilistic System-One policy and are measuring "
                        "the effect on simulation throughput and behavior."
                    ),
                },
                {
                    "poster_agent_id": min(1, count - 1),
                    "content": (
                        "A useful benchmark should compare identical initial "
                        "societies under an LLM-only policy and a hybrid policy, "
                        "not just report a cherry-picked run."
                    ),
                },
            ]
        },
        "jevfish": {
            "decision_engine": mode,
            "policy_mode": "multi",
        },
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def database_summary(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    summary: dict[str, Any] = {}

    for table in ("user", "post", "follow", "trace"):
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            summary[f"{table}_rows"] = int(cursor.fetchone()[0])
        except sqlite3.Error:
            summary[f"{table}_rows"] = None

    try:
        cursor.execute(
            "SELECT action, COUNT(*) FROM trace "
            "GROUP BY action ORDER BY COUNT(*) DESC"
        )
        summary["trace_actions"] = {
            str(action): int(count)
            for action, count in cursor.fetchall()
        }
    except sqlite3.Error:
        summary["trace_actions"] = {}

    connection.close()
    return summary


def adjusted_behavior_counts(raw: dict[str, int]) -> dict[str, int]:
    counts = {
        str(action): int(count)
        for action, count in raw.items()
        if action != "sign_up" and int(count) > 0
    }
    if "create_post" in counts:
        counts["create_post"] = max(
            0, counts["create_post"] - SEED_POST_COUNT
        )
        if counts["create_post"] == 0:
            counts.pop("create_post")
    return counts


def distribution_similarity(
    a: dict[str, int],
    b: dict[str, int],
) -> float:
    """1 - total variation distance over action-frequency distributions."""
    labels = set(a) | set(b)
    total_a = sum(a.values())
    total_b = sum(b.values())
    if total_a == 0 and total_b == 0:
        return 1.0
    if total_a == 0 or total_b == 0:
        return 0.0

    l1 = 0.0
    for label in labels:
        pa = a.get(label, 0) / total_a
        pb = b.get(label, 0) / total_b
        l1 += abs(pa - pb)
    return max(0.0, 1.0 - 0.5 * l1)


def parse_loop_seconds(output: str) -> float | None:
    patterns = [
        r"总耗时:\s*([0-9.]+)秒",
        r"total\s+time:\s*([0-9.]+)\s*s",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def run_arm(
    mode: str,
    *,
    agents: int,
    rounds: int,
    threshold: float,
    max_actions: int,
) -> dict[str, Any]:
    people = make_people(agents)

    with tempfile.TemporaryDirectory(prefix=f"jevfish-ab-{mode}-") as tmp:
        sim_dir = Path(tmp)
        write_profiles(sim_dir / "twitter_profiles.csv", people)
        write_config(
            sim_dir / "simulation_config.json",
            people,
            rounds=rounds,
            mode=mode,
        )

        env = os.environ.copy()
        env.update(
            {
                "JEVFISH_DECISION_ENGINE": mode,
                "JEVFISH_POLICY_MODE": "multi",
                "JEVFISH_SAMPLE_PROBABILITIES": "false",
                "JEVFISH_CONFIDENCE_THRESHOLD": str(threshold),
                "JEVFISH_MAX_ACTIONS_PER_AGENT": str(max_actions),
                "JEVFISH_MAX_SYSTEM_TWO_ACTIONS": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )

        command = [
            sys.executable,
            str(RUNNER),
            "--config",
            str(sim_dir / "simulation_config.json"),
            "--max-rounds",
            str(rounds),
            "--no-wait",
        ]

        start = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(300, agents * rounds * 30),
            check=False,
        )
        elapsed_seconds = time.perf_counter() - start
        output = completed.stdout

        metrics_path = sim_dir / "jevfish_twitter_metrics.json"
        db_path = sim_dir / "twitter_simulation.db"

        result: dict[str, Any] = {
            "mode": mode,
            "exit_code": completed.returncode,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "loop_seconds": parse_loop_seconds(output),
            "stdout_tail": output[-5000:],
        }
        if metrics_path.exists():
            result["metrics"] = json.loads(
                metrics_path.read_text(encoding="utf-8")
            )
        if db_path.exists():
            result["database"] = database_summary(db_path)

        if completed.returncode != 0:
            raise RuntimeError(
                f"{mode} arm failed with exit code "
                f"{completed.returncode}\n{output[-5000:]}"
            )
        if not metrics_path.exists() or not db_path.exists():
            raise RuntimeError(
                f"{mode} arm did not write expected metrics/database"
            )
        return result


def compare(
    hybrid: dict[str, Any],
    llm: dict[str, Any],
    *,
    agents: int,
    rounds: int,
) -> dict[str, Any]:
    hybrid_metrics = hybrid["metrics"]
    llm_metrics = llm["metrics"]

    hybrid_actions = adjusted_behavior_counts(
        hybrid["database"].get("trace_actions", {})
    )
    llm_actions = adjusted_behavior_counts(
        llm["database"].get("trace_actions", {})
    )

    full_llm_turns = int(hybrid_metrics.get("llm_fallbacks", 0))
    system_two_successes = int(hybrid_metrics.get("system_two_calls", 0))
    system_two_errors = int(hybrid_metrics.get("system_two_errors", 0))
    system_two_requests = int(
        hybrid_metrics.get(
            "system_two_requests",
            system_two_successes + system_two_errors,
        )
    )
    hybrid_expensive_requests_or_turns = full_llm_turns + system_two_requests
    baseline_llm_turns = int(llm_metrics.get("llm_fallbacks", 0))
    expensive_delta = baseline_llm_turns - hybrid_expensive_requests_or_turns

    hybrid_time = hybrid.get("loop_seconds") or hybrid["elapsed_seconds"]
    llm_time = llm.get("loop_seconds") or llm["elapsed_seconds"]

    return {
        "agent_rounds": agents * rounds,
        "hybrid_full_llm_agent_turns": full_llm_turns,
        "hybrid_system_two_requests": system_two_requests,
        "hybrid_system_two_successes": system_two_successes,
        "hybrid_system_two_errors": system_two_errors,
        "hybrid_expensive_model_requests_or_turns": hybrid_expensive_requests_or_turns,
        "baseline_llm_agent_turns": baseline_llm_turns,
        "expensive_request_or_turn_delta": expensive_delta,
        "expensive_request_or_turn_reduction_pct": (
            round(100 * expensive_delta / baseline_llm_turns, 2)
            if baseline_llm_turns
            else None
        ),
        "runtime_speedup": (
            round(float(llm_time) / float(hybrid_time), 3)
            if hybrid_time
            else None
        ),
        "hybrid_behavior_actions": hybrid_actions,
        "llm_behavior_actions": llm_actions,
        "action_distribution_similarity": round(
            distribution_similarity(hybrid_actions, llm_actions),
            4,
        ),
        "hybrid_generated_posts": hybrid_actions.get("create_post", 0),
        "llm_generated_posts": llm_actions.get("create_post", 0),
        "hybrid_follow_actions": hybrid_actions.get("follow", 0),
        "llm_follow_actions": llm_actions.get("follow", 0),
        "hybrid_like_actions": hybrid_actions.get("like_post", 0),
        "llm_like_actions": llm_actions.get("like_post", 0),
        "note": (
            "A constrained System-Two request and a full OASIS LLM agent turn "
            "are different workloads, so request/turn counts are reported "
            "separately as well as combined. Action-distribution similarity "
            "is descriptive agreement between these two simulation policies, "
            "not real-world predictive accuracy."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=0.58)
    parser.add_argument("--max-actions", type=int, default=3)
    parser.add_argument(
        "--output",
        default="jevfish-ab-report.json",
    )
    args = parser.parse_args()

    if args.agents < 2:
        raise SystemExit("--agents must be >= 2")
    if args.rounds < 1:
        raise SystemExit("--rounds must be >= 1")

    require_env("TYPESAFE_API_KEY")
    require_env("LLM_API_KEY")
    require_env("LLM_MODEL_NAME")

    report: dict[str, Any] = {
        "config": {
            "agents": args.agents,
            "rounds": args.rounds,
            "threshold": args.threshold,
            "max_actions": args.max_actions,
            "jev_model": os.environ.get(
                "TYPESAFE_DEFAULT_MODEL", "jev-latest"
            ),
            "llm_model": os.environ.get("LLM_MODEL_NAME"),
            "llm_base_url": os.environ.get("LLM_BASE_URL"),
        }
    }

    try:
        report["hybrid"] = run_arm(
            "hybrid",
            agents=args.agents,
            rounds=args.rounds,
            threshold=args.threshold,
            max_actions=args.max_actions,
        )
        report["llm"] = run_arm(
            "llm",
            agents=args.agents,
            rounds=args.rounds,
            threshold=args.threshold,
            max_actions=args.max_actions,
        )
        report["comparison"] = compare(
            report["hybrid"],
            report["llm"],
            agents=args.agents,
            rounds=args.rounds,
        )
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        Path(args.output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise

    Path(args.output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
