"""Validate the production OASIS -> CAMEL -> OpenRouter System-Two path.

Uses the same five-agent synthetic society as the hybrid integration test but
forces JevFish into `llm` mode. This confirms the configured OpenRouter model
can drive OASIS LLMAction calls, and provides a first baseline against the
hybrid Jev run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from live_jevfish_oasis import ROOT, RUNNER, sqlite_summary, write_config, write_profiles

REPORT_PATH = Path(
    os.environ.get("JEVFISH_OASIS_LLM_REPORT", "jevfish-oasis-llm-live.json")
)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    require_env("LLM_API_KEY")

    report: dict[str, object] = {
        "model": os.environ.get("LLM_MODEL_NAME"),
        "llm_base_url": os.environ.get("LLM_BASE_URL"),
        "decision_engine": "llm",
        "agents": 5,
        "rounds": 1,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="jevfish-oasis-llm-") as tmp:
            sim_dir = Path(tmp)
            write_profiles(sim_dir / "twitter_profiles.csv")
            write_config(sim_dir / "simulation_config.json")

            env = os.environ.copy()
            env.update(
                {
                    "JEVFISH_DECISION_ENGINE": "llm",
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
                timeout=300,
                check=False,
            )
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            output = completed.stdout

            report["exit_code"] = completed.returncode
            report["elapsed_ms"] = elapsed_ms
            report["stdout_tail"] = output[-16000:]

            metrics_path = sim_dir / "jevfish_twitter_metrics.json"
            db_path = sim_dir / "twitter_simulation.db"
            if metrics_path.exists():
                report["jevfish_metrics"] = json.loads(
                    metrics_path.read_text(encoding="utf-8")
                )
            if db_path.exists():
                report["database"] = sqlite_summary(db_path)

            if completed.returncode != 0:
                raise AssertionError(
                    "Production OASIS LLM baseline exited with "
                    f"{completed.returncode}\n{output[-8000:]}"
                )
            if not metrics_path.exists():
                raise AssertionError("JevFish metrics file was not written")
            if not db_path.exists():
                raise AssertionError("OASIS Twitter SQLite database was not created")

            metrics = report["jevfish_metrics"]
            assert isinstance(metrics, dict)
            if metrics.get("mode") != "llm":
                raise AssertionError(f"Expected llm mode metrics: {metrics}")
            if int(metrics.get("jev_calls", 0)) != 0:
                raise AssertionError(f"LLM baseline unexpectedly called Jev: {metrics}")
            if int(metrics.get("llm_fallbacks", 0)) < 1:
                raise AssertionError(f"Expected upstream LLMAction calls: {metrics}")

            database = report["database"]
            assert isinstance(database, dict)
            if int(database.get("trace_rows") or 0) < 3:
                raise AssertionError(
                    f"Expected OASIS to persist baseline actions: {database}"
                )

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
