"""Run JevFish through the real OASIS Twitter simulation entrypoint.

This is intentionally a live integration test. It creates a tiny synthetic
five-agent society, runs one real simulation round, then verifies that:

- the production JevFish wrapper starts correctly;
- OASIS creates and mutates a real SQLite social world;
- TypeSafe Jev is called for active agents;
- structured decisions execute inside OASIS;
- any System-Two fallbacks use the configured OpenAI-compatible provider;
- JevFish metrics are persisted when the environment closes.

No Zep key is required because this test starts after the graph/persona
preparation stage and directly exercises the social simulation runtime.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "backend" / "scripts" / "run_twitter_simulation.py"
REPORT_PATH = Path(os.environ.get("JEVFISH_OASIS_REPORT", "jevfish-oasis-live.json"))


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def write_profiles(path: Path) -> None:
    rows = [
        {
            "name": "Asha Rao",
            "username": "asha_sys",
            "user_char": "Pragmatic systems engineer. Likes concrete benchmarks and open-source infrastructure; rarely posts without a reason.",
            "description": "Systems engineer working on agent infrastructure.",
            "following_agentid_list": "[1, 2]",
            "previous_tweets": "[]",
        },
        {
            "name": "Ben Li",
            "username": "ben_bench",
            "user_char": "Skeptical performance researcher. Engages with reproducible benchmarks and challenges vague claims.",
            "description": "Researcher focused on reproducibility and evaluation.",
            "following_agentid_list": "[0, 2]",
            "previous_tweets": "[]",
        },
        {
            "name": "Cara Stone",
            "username": "cara_agents",
            "user_char": "AI infrastructure researcher. Curious about fast decision models, multi-agent systems, and scaling experiments.",
            "description": "AI infrastructure researcher.",
            "following_agentid_list": "[0, 1, 3]",
            "previous_tweets": "[]",
        },
        {
            "name": "Diego Park",
            "username": "diego_oss",
            "user_char": "Open-source maintainer. Tends to like useful engineering work, repost practical releases, and ignore hype.",
            "description": "Open-source maintainer and backend developer.",
            "following_agentid_list": "[0, 2, 4]",
            "previous_tweets": "[]",
        },
        {
            "name": "Eva Chen",
            "username": "eva_product",
            "user_char": "Developer-tools product engineer. Interested in user-visible speedups and thoughtful product experiments.",
            "description": "Developer-tools product engineer.",
            "following_agentid_list": "[0, 2, 3]",
            "previous_tweets": "[]",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_config(path: Path) -> None:
    agents = []
    bios = [
        "Pragmatic systems engineer who likes benchmarks and open source.",
        "Skeptical performance researcher focused on reproducibility.",
        "AI infrastructure researcher interested in multi-agent systems.",
        "Open-source maintainer who prefers practical engineering over hype.",
        "Developer-tools product engineer interested in visible speedups.",
    ]
    for agent_id, bio in enumerate(bios):
        agents.append(
            {
                "agent_id": agent_id,
                "entity_name": ["Asha", "Ben", "Cara", "Diego", "Eva"][agent_id],
                "bio": bio,
                "activity_level": 1.0,
                "active_hours": list(range(24)),
            }
        )

    config = {
        "simulation_id": "jevfish_live_oasis",
        "llm_model": os.environ.get("LLM_MODEL_NAME", "meta/muse-spark-1.3-contributor"),
        "agent_configs": agents,
        "time_config": {
            "total_simulation_hours": 1,
            "minutes_per_round": 60,
            "agents_per_hour_min": 5,
            "agents_per_hour_max": 5,
            "peak_hours": [],
            "off_peak_hours": [],
            "peak_activity_multiplier": 1.0,
            "off_peak_activity_multiplier": 1.0,
        },
        "event_config": {
            "initial_posts": [
                {
                    "poster_agent_id": 0,
                    "content": "We replaced many tiny generative-agent decisions with a fast probabilistic System-One layer and are measuring the effect on simulation throughput.",
                },
                {
                    "poster_agent_id": 1,
                    "content": "A useful benchmark should compare the same initial society under an LLM-only policy and a hybrid policy, not just report a cherry-picked run.",
                },
            ]
        },
        "jevfish": {"decision_engine": "hybrid"},
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def sqlite_summary(db_path: Path) -> dict:
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    summary: dict[str, object] = {}

    for table in ("user", "post", "follow", "trace"):
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            summary[f"{table}_rows"] = int(cursor.fetchone()[0])
        except sqlite3.Error:
            summary[f"{table}_rows"] = None

    try:
        cursor.execute(
            "SELECT action, COUNT(*) FROM trace GROUP BY action ORDER BY COUNT(*) DESC"
        )
        summary["trace_actions"] = {str(action): int(count) for action, count in cursor.fetchall()}
    except sqlite3.Error:
        summary["trace_actions"] = {}

    connection.close()
    return summary


def main() -> None:
    require_env("TYPESAFE_API_KEY")
    require_env("LLM_API_KEY")

    report: dict[str, object] = {
        "model": os.environ.get("LLM_MODEL_NAME"),
        "llm_base_url": os.environ.get("LLM_BASE_URL"),
        "decision_engine": "hybrid",
        "agents": 5,
        "rounds": 1,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="jevfish-oasis-") as tmp:
            sim_dir = Path(tmp)
            write_profiles(sim_dir / "twitter_profiles.csv")
            write_config(sim_dir / "simulation_config.json")

            env = os.environ.copy()
            env.update(
                {
                    "JEVFISH_DECISION_ENGINE": "hybrid",
                    "JEVFISH_SAMPLE_PROBABILITIES": "false",
                    "JEVFISH_CONFIDENCE_THRESHOLD": "0.0",
                    "JEVFISH_MAX_CONTEXT_POSTS": "12",
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
                "1",
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
                timeout=240,
                check=False,
            )
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            output = completed.stdout

            report["exit_code"] = completed.returncode
            report["elapsed_ms"] = elapsed_ms
            report["stdout_tail"] = output[-12000:]

            metrics_path = sim_dir / "jevfish_twitter_metrics.json"
            db_path = sim_dir / "twitter_simulation.db"
            if metrics_path.exists():
                report["jevfish_metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
            if db_path.exists():
                report["database"] = sqlite_summary(db_path)

            if completed.returncode != 0:
                raise AssertionError(
                    f"Production JevFish Twitter runner exited with {completed.returncode}\n{output[-6000:]}"
                )
            if not metrics_path.exists():
                raise AssertionError("JevFish metrics file was not written by the production environment proxy")
            if not db_path.exists():
                raise AssertionError("OASIS Twitter SQLite database was not created")

            metrics = report["jevfish_metrics"]
            assert isinstance(metrics, dict)
            if int(metrics.get("jev_calls", 0)) < 1:
                raise AssertionError(f"Expected at least one live Jev decision: {metrics}")
            if int(metrics.get("errors", 0)) != 0:
                raise AssertionError(f"Jev errors were recorded: {metrics}")

            database = report["database"]
            assert isinstance(database, dict)
            if int(database.get("trace_rows") or 0) < 3:
                raise AssertionError(f"Expected OASIS to record seed + simulated actions: {database}")

            report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        raise

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
