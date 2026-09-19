"""Robust System-Two text materialization for JevFish production entrypoints.

Muse Spark and other reasoning models can spend a small completion budget on
reasoning and return no visible text. JevFish needs language generation to be a
bounded materialization step, not an opaque full-agent retry loop, so this
adapter retries an empty completion once with a larger budget and records every
provider request in the JevFish metrics.
"""

from __future__ import annotations

import json
import time
import types
from typing import Any, Optional


async def _generate_text_with_retry(
    self: Any,
    *,
    kind: str,
    agent: Any,
    platform: str,
    posts: list[dict[str, Any]],
    target: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    client = await self._ensure_llm_client()
    if client is None:
        return None

    self.stats.setdefault("system_two_requests", 0)
    self.stats.setdefault("system_two_retries", 0)
    self.stats.setdefault("system_two_empty_responses", 0)
    self.stats.setdefault("system_two_latency_ms", 0.0)

    persona = json.dumps(
        self._persona(agent),
        ensure_ascii=False,
    )
    recent_feed = json.dumps(
        [
            {
                "author": post["author"],
                "content": post["content"],
            }
            for post in posts[:6]
        ],
        ensure_ascii=False,
    )

    if kind == "create_post":
        task = (
            "Write one plausible standalone social-media post this "
            "person would publish now."
        )
    elif kind == "quote":
        task = (
            "Write only the short commentary this person would add "
            "while quote-posting the target."
        )
    else:
        task = (
            "Write only the comment this person would leave on the "
            "target post."
        )

    target_text = ""
    if target is not None:
        target_text = (
            "\nTarget post:\n"
            f"author={target['author']}\n"
            f"content={target['content']}"
        )

    prompt = (
        f"Platform: {platform}\n"
        f"Persona: {persona}\n"
        f"Recent feed: {recent_feed}"
        f"{target_text}\n\n"
        f"{task}\n"
        "Preserve the persona. Be natural, concise, and specific. "
        "Return visible social text, not analysis. Do not explain your "
        "answer or wrap it in quotes. Avoid generic AI-style enthusiasm. "
        "Use hashtags only if this persona would naturally use them."
    )

    base_kwargs: dict[str, Any] = {
        "model": self.llm_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You materialize a simulated person's already-chosen "
                    "social action into natural language. Output only the "
                    "requested visible social text."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }
    if self.llm_base_url and "openrouter.ai" in self.llm_base_url:
        base_kwargs["extra_body"] = {
            "reasoning": {"effort": "low"}
        }

    # The first budget is deliberately moderate. The retry is only used when a
    # reasoning model returns an empty visible message or an exception.
    attempts = (512, 1024)
    last_error: Optional[Exception] = None

    for attempt_index, max_tokens in enumerate(attempts):
        kwargs = dict(base_kwargs)
        kwargs["max_tokens"] = max_tokens
        self.stats["system_two_requests"] += 1
        if attempt_index:
            self.stats["system_two_retries"] += 1

        started = time.perf_counter()
        try:
            response = await client.chat.completions.create(**kwargs)
            self.stats["system_two_latency_ms"] += round(
                (time.perf_counter() - started) * 1000,
                1,
            )

            choice = response.choices[0]
            text = (choice.message.content or "").strip()
            if text:
                self.stats["system_two_calls"] += 1
                bucket = self.stats["system_two_by_type"]
                bucket[kind] = int(bucket.get(kind, 0)) + 1
                return text[:1200]

            self.stats["system_two_empty_responses"] += 1
            finish_reason = getattr(choice, "finish_reason", None)
            last_error = RuntimeError(
                "System-Two returned empty visible text"
                f" (finish_reason={finish_reason!r}, max_tokens={max_tokens})"
            )
        except Exception as exc:
            self.stats["system_two_latency_ms"] += round(
                (time.perf_counter() - started) * 1000,
                1,
            )
            last_error = exc

    self.stats["system_two_errors"] += 1
    print(
        f"[JevFish] System-Two generation failed for {kind} "
        f"after {len(attempts)} attempts: {last_error}"
    )
    return None


def install_system_two_retry(engine: Any) -> Any:
    """Install robust text materialization on one JevDecisionEngine instance."""
    engine.stats.setdefault("system_two_requests", 0)
    engine.stats.setdefault("system_two_retries", 0)
    engine.stats.setdefault("system_two_empty_responses", 0)
    engine.stats.setdefault("system_two_latency_ms", 0.0)
    engine._generate_text = types.MethodType(
        _generate_text_with_retry,
        engine,
    )
    return engine
