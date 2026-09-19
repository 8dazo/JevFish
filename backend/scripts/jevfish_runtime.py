"""JevFish runtime adapter for OASIS simulations.

This module keeps the upstream MiroFish/OASIS simulation code intact and wraps
OASIS environments at runtime. Whenever an upstream simulation submits an
``LLMAction()``, JevFish can replace it with a cheap structured ``ManualAction``
for actions that do not require free-form text. Ambiguous or generative actions
fall back to the original LLM path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


DEFAULT_MODE = "hybrid"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Convert arbitrary profile/config objects to a compact JSON-safe value."""
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value), depth=depth + 1)
    if isinstance(value, Mapping):
        return {
            str(k): _json_safe(v, depth=depth + 1)
            for k, v in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, depth=depth + 1) for v in list(value)[:40]]
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(), depth=depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            public = {k: v for k, v in vars(value).items() if not k.startswith("_")}
            return _json_safe(public, depth=depth + 1)
        except Exception:
            pass
    return str(value)


def _platform_name(platform: Any) -> str:
    raw = getattr(platform, "value", platform)
    text = str(raw).lower()
    if "reddit" in text:
        return "reddit"
    return "twitter"


def _agent_id(agent: Any) -> int:
    for name in ("agent_id", "id"):
        value = getattr(agent, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return -1


def _load_config_from_argv() -> Dict[str, Any]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    args, _ = parser.parse_known_args()
    if not args.config:
        return {}
    try:
        with open(args.config, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        print(f"[JevFish] unable to load simulation config: {exc}")
        return {}


class JevDecisionEngine:
    """Turn high-frequency OASIS LLM actions into Jev-backed manual actions."""

    def __init__(self, legacy_module: Any, config: Dict[str, Any]) -> None:
        self.legacy = legacy_module
        self.config = config
        configured = str(
            config.get("jevfish", {}).get("decision_engine", "")
            if isinstance(config.get("jevfish"), dict)
            else ""
        ).strip().lower()
        self.mode = os.getenv("JEVFISH_DECISION_ENGINE", configured or DEFAULT_MODE).strip().lower()
        if self.mode not in {"llm", "hybrid", "jev"}:
            print(f"[JevFish] unknown decision engine {self.mode!r}; using {DEFAULT_MODE}")
            self.mode = DEFAULT_MODE

        self.threshold = float(os.getenv("JEVFISH_CONFIDENCE_THRESHOLD", "0.58"))
        self.max_posts = max(1, min(30, int(os.getenv("JEVFISH_MAX_CONTEXT_POSTS", "12"))))
        self.sample_probabilities = _env_bool("JEVFISH_SAMPLE_PROBABILITIES", True)
        self.api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
        self.model = os.getenv("TYPESAFE_DEFAULT_MODEL", "jev-latest").strip() or "jev-latest"
        self._client: Any = None
        self._warned_missing_key = False
        self.stats: Dict[str, Any] = {
            "mode": self.mode,
            "jev_calls": 0,
            "jev_manual_actions": 0,
            "llm_fallbacks": 0,
            "passthrough_actions": 0,
            "errors": 0,
            "manual_by_type": {},
        }
        self._agent_configs = {
            int(item.get("agent_id", -1)): item
            for item in config.get("agent_configs", [])
            if isinstance(item, dict)
        }

    def _llm_action(self) -> Any:
        self.stats["llm_fallbacks"] += 1
        return self.legacy.LLMAction()

    def _manual_action(self, action_type: Any, action_args: Dict[str, Any]) -> Any:
        name = getattr(action_type, "name", str(action_type))
        bucket = self.stats["manual_by_type"]
        bucket[name] = int(bucket.get(name, 0)) + 1
        self.stats["jev_manual_actions"] += 1
        return self.legacy.ManualAction(action_type=action_type, action_args=action_args)

    async def _ensure_client(self) -> Optional[Any]:
        if self.mode == "llm":
            return None
        if not self.api_key:
            if self.mode == "jev":
                raise RuntimeError("JEVFISH_DECISION_ENGINE=jev requires TYPESAFE_API_KEY")
            if not self._warned_missing_key:
                print("[JevFish] TYPESAFE_API_KEY missing; hybrid mode is falling back to LLMAction")
                self._warned_missing_key = True
            return None
        if self._client is None:
            from typesafe_sdk import AsyncTypeSafeClient
            self._client = AsyncTypeSafeClient(api_key=self.api_key, model=self.model)
        return self._client

    def _persona(self, agent: Any) -> Any:
        aid = _agent_id(agent)
        configured = self._agent_configs.get(aid)
        if configured:
            return _json_safe(configured)
        return _json_safe(getattr(agent, "user_info", {"agent_id": aid}))

    def _recent_posts(self, db_path: str, aid: int) -> list[dict[str, Any]]:
        if not db_path or not os.path.exists(db_path):
            return []
        try:
            connection = sqlite3.connect(db_path)
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT p.post_id, p.content, p.user_id, u.agent_id, u.name, u.user_name
                FROM post p
                LEFT JOIN user u ON p.user_id = u.user_id
                ORDER BY p.post_id DESC
                LIMIT ?
                """,
                (self.max_posts * 2,),
            )
            rows = cursor.fetchall()
            connection.close()
        except Exception:
            return []

        posts: list[dict[str, Any]] = []
        for post_id, content, user_id, author_agent_id, name, user_name in rows:
            if author_agent_id is not None and int(author_agent_id) == aid:
                continue
            posts.append(
                {
                    "key": f"post_{int(post_id)}",
                    "post_id": int(post_id),
                    "content": (content or "")[:800],
                    "author_user_id": int(user_id) if user_id is not None else None,
                    "author_agent_id": int(author_agent_id) if author_agent_id is not None else None,
                    "author": name or user_name or f"user_{user_id}",
                }
            )
            if len(posts) >= self.max_posts:
                break
        return posts

    @staticmethod
    def _sample_choice(answer: Any, *, stochastic: bool) -> str:
        if not stochastic:
            return str(answer.choice)
        probabilities = getattr(answer, "probabilities", None) or {}
        labels = list(probabilities.keys())
        weights = [max(0.0, float(probabilities[label])) for label in labels]
        if labels and sum(weights) > 0:
            return str(random.choices(labels, weights=weights, k=1)[0])
        return str(answer.choice)

    async def decide(self, agent: Any, *, db_path: str, platform: str) -> Any:
        if self.mode == "llm":
            return self._llm_action()

        client = await self._ensure_client()
        if client is None:
            return self._llm_action()

        aid = _agent_id(agent)
        posts = self._recent_posts(db_path, aid)
        if not posts:
            return self._llm_action()

        action_criteria = {
            "do_nothing": "Ignore the current feed and take no social action.",
            "like_post": "Like one existing post that this persona would positively react to.",
            "follow_author": "Follow the author of one existing post when the persona would want more from them.",
            "generate": "The persona should create original language: make a post, reply, quote, search, or otherwise do something requiring text generation.",
        }
        if platform == "twitter":
            action_criteria["repost"] = "Repost an existing post without adding text."
        else:
            action_criteria["dislike_post"] = "Downvote/dislike an existing post."

        target_criteria = {
            post["key"]: {"author": post["author"], "content": post["content"]}
            for post in posts
        }
        target_criteria["none"] = "No existing post should be targeted."

        state = {
            "platform": platform,
            "persona": self._persona(agent),
            "recent_feed": [
                {"key": post["key"], "author": post["author"], "content": post["content"]}
                for post in posts
            ],
            "instruction": (
                "Act as this simulated person's fast intuitive behavior. "
                "Prefer do_nothing when there is no natural reason to engage. "
                "Do not optimize for engagement; preserve the persona."
            ),
        }

        try:
            from typesafe_sdk import Choice
            response = await client.system_one(
                state=state,
                questions={
                    "action": Choice(
                        instructions="What kind of action would this persona take right now?",
                        criteria=action_criteria,
                    ),
                    "target": Choice(
                        instructions="Which feed post best matches the action, if an existing post is needed?",
                        criteria=target_criteria,
                    ),
                },
            )
            self.stats["jev_calls"] += 1
            action_answer = response.choices["action"]
            target_answer = response.choices["target"]
        except Exception as exc:
            self.stats["errors"] += 1
            print(f"[JevFish] Jev decision failed for agent {aid}: {exc}")
            if self.mode == "jev":
                return self._manual_action(self.legacy.ActionType.DO_NOTHING, {})
            return self._llm_action()

        if float(action_answer.confidence) < self.threshold:
            return self._llm_action()

        action = self._sample_choice(action_answer, stochastic=self.sample_probabilities)
        if action == "generate":
            return self._llm_action()
        if action == "do_nothing":
            return self._manual_action(self.legacy.ActionType.DO_NOTHING, {})

        if float(target_answer.confidence) < self.threshold:
            return self._llm_action()
        target_key = self._sample_choice(target_answer, stochastic=self.sample_probabilities)
        target = next((post for post in posts if post["key"] == target_key), None)
        if not target:
            return self._llm_action()

        if action == "like_post":
            return self._manual_action(self.legacy.ActionType.LIKE_POST, {"post_id": target["post_id"]})
        if action == "repost" and platform == "twitter":
            return self._manual_action(self.legacy.ActionType.REPOST, {"post_id": target["post_id"]})
        if action == "dislike_post" and platform == "reddit":
            return self._manual_action(self.legacy.ActionType.DISLIKE_POST, {"post_id": target["post_id"]})
        if action == "follow_author" and target.get("author_user_id") is not None:
            return self._manual_action(self.legacy.ActionType.FOLLOW, {"followee_id": target["author_user_id"]})

        return self._llm_action()

    async def transform_actions(
        self,
        actions: Mapping[Any, Any],
        *,
        db_path: str,
        platform: str,
    ) -> Dict[Any, Any]:
        """Replace only bare upstream LLMAction values; preserve manual/interview actions."""
        transformed: Dict[Any, Any] = {}
        pending: list[tuple[Any, Any]] = []

        for agent, action in actions.items():
            if isinstance(action, self.legacy.LLMAction):
                pending.append((agent, action))
            else:
                transformed[agent] = action
                self.stats["passthrough_actions"] += 1

        if pending:
            decisions = await asyncio.gather(
                *(self.decide(agent, db_path=db_path, platform=platform) for agent, _ in pending)
            )
            for (agent, _), decision in zip(pending, decisions):
                transformed[agent] = decision

        return transformed

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class JevEnvironmentProxy:
    def __init__(self, env: Any, engine: JevDecisionEngine, *, db_path: str, platform: str) -> None:
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_engine", engine)
        object.__setattr__(self, "_db_path", db_path)
        object.__setattr__(self, "_platform", platform)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._env, name, value)

    async def step(self, actions: Mapping[Any, Any]) -> Any:
        transformed = await self._engine.transform_actions(
            actions,
            db_path=self._db_path,
            platform=self._platform,
        )
        return await self._env.step(transformed)

    async def close(self) -> Any:
        self._write_metrics()
        return await self._env.close()

    def _write_metrics(self) -> None:
        try:
            path = Path(self._db_path).parent / f"jevfish_{self._platform}_metrics.json"
            payload = dict(self._engine.stats)
            payload["platform"] = self._platform
            payload["database"] = self._db_path
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"[JevFish] unable to write metrics: {exc}")


def install_jevfish(legacy_module: Any) -> JevDecisionEngine:
    """Patch an imported legacy simulator so all newly-created OASIS envs are proxied."""
    config = _load_config_from_argv()
    engine = JevDecisionEngine(legacy_module, config)
    original_make = legacy_module.oasis.make

    def make_with_jev(*args: Any, **kwargs: Any) -> Any:
        env = original_make(*args, **kwargs)
        db_path = str(kwargs.get("database_path") or "")
        platform = _platform_name(kwargs.get("platform"))
        return JevEnvironmentProxy(env, engine, db_path=db_path, platform=platform)

    legacy_module.oasis.make = make_with_jev
    print(
        "[JevFish] decision engine="
        f"{engine.mode}, model={engine.model}, threshold={engine.threshold:.2f}, "
        f"sampling={'on' if engine.sample_probabilities else 'off'}"
    )
    return engine
