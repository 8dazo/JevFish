"""Live-network smoke test for JevFish.

This test intentionally uses real provider credentials from environment variables.
It validates:
1. JevFish can call TypeSafe Jev through the real SDK.
2. A Jev decision can be transformed into the runtime's structured action path.
3. The configured OpenAI-compatible System-Two provider is reachable.

It is not part of the normal unit test suite. Run it from the dedicated
GitHub Actions workflow with repository secrets configured.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from jevfish_runtime import JevDecisionEngine  # noqa: E402


class ActionType(Enum):
    DO_NOTHING = "do_nothing"
    LIKE_POST = "like_post"
    REPOST = "repost"
    DISLIKE_POST = "dislike_post"
    FOLLOW = "follow"


class LLMAction:
    pass


@dataclass
class ManualAction:
    action_type: ActionType
    action_args: dict


@dataclass
class Agent:
    agent_id: int
    user_info: dict


def build_db(path: str) -> None:
    connection = sqlite3.connect(path)
    cursor = connection.cursor()
    cursor.execute(
        "CREATE TABLE user (user_id INTEGER PRIMARY KEY, agent_id INTEGER, name TEXT, user_name TEXT)"
    )
    cursor.execute(
        "CREATE TABLE post (post_id INTEGER PRIMARY KEY, content TEXT, user_id INTEGER)"
    )
    cursor.execute(
        "INSERT INTO user(user_id, agent_id, name, user_name) VALUES (1, 2, 'Ada', 'ada')"
    )
    cursor.execute(
        "INSERT INTO user(user_id, agent_id, name, user_name) VALUES (2, 3, 'Lin', 'lin')"
    )
    cursor.execute(
        "INSERT INTO post(post_id, content, user_id) VALUES (?, ?, ?)",
        (
            101,
            "A new open-source systems paper shows a practical technique for making agent runtimes faster while preserving behavior.",
            1,
        ),
    )
    cursor.execute(
        "INSERT INTO post(post_id, content, user_id) VALUES (?, ?, ?)",
        (
            102,
            "A detailed benchmark compares probabilistic decision engines across many repeated simulation runs.",
            2,
        ),
    )
    connection.commit()
    connection.close()


async def check_jev() -> dict:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise RuntimeError("TYPESAFE_API_KEY is missing")

    os.environ["JEVFISH_DECISION_ENGINE"] = "hybrid"
    os.environ["JEVFISH_CONFIDENCE_THRESHOLD"] = "0.0"
    os.environ["JEVFISH_SAMPLE_PROBABILITIES"] = "false"

    legacy = SimpleNamespace(
        LLMAction=LLMAction,
        ManualAction=ManualAction,
        ActionType=ActionType,
    )
    config = {
        "agent_configs": [
            {
                "agent_id": 1,
                "name": "Dev",
                "bio": "A quiet systems engineer interested in agent runtimes and open-source infrastructure.",
                "activity_level": 0.5,
            }
        ]
    }
    engine = JevDecisionEngine(legacy, config)
    agent = Agent(agent_id=1, user_info=config["agent_configs"][0])

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "twitter.db")
        build_db(db_path)
        start = time.perf_counter()
        action = await engine.decide(agent, db_path=db_path, platform="twitter")
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

    result = {
        "provider": "typesafe",
        "model": engine.model,
        "latency_ms": latency_ms,
        "returned_type": type(action).__name__,
        "action_type": (
            action.action_type.name if isinstance(action, ManualAction) else "LLM_FALLBACK"
        ),
        "action_args": action.action_args if isinstance(action, ManualAction) else {},
        "stats": engine.stats,
    }
    await engine.close()

    if engine.stats["errors"] != 0:
        raise AssertionError(f"Jev call recorded errors: {engine.stats}")
    if engine.stats["jev_calls"] != 1:
        raise AssertionError(f"Expected exactly one successful Jev call: {engine.stats}")

    return result


async def check_llm() -> dict:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL_NAME", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip() or None
    if not api_key or not model:
        return {"provider": "llm", "skipped": True, "reason": "LLM_API_KEY or LLM_MODEL_NAME missing"}

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    start = time.perf_counter()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly the single word READY.",
            }
        ],
        # Muse Spark is a reasoning model: leave enough room for reasoning + visible output.
        max_tokens=256,
        temperature=0,
        extra_body={"reasoning": {"effort": "low"}},
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    message = response.choices[0].message
    text = (message.content or "").strip()
    await client.close()

    if "READY" not in text.upper():
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        raise AssertionError(
            f"Unexpected LLM smoke-test response: {text!r}; finish_reason={finish_reason!r}"
        )

    return {
        "provider": "llm",
        "model": model,
        "base_url": base_url or "provider default",
        "latency_ms": latency_ms,
        "response": text,
        "finish_reason": getattr(response.choices[0], "finish_reason", None),
    }


async def main() -> None:
    output = Path(os.environ.get("JEVFISH_SMOKE_REPORT", "jevfish-live-smoke.json"))
    report: dict = {}

    try:
        report["jev"] = await check_jev()
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")

        report["llm"] = await check_llm()
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        raise

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
