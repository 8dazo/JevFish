"""Observation adapter that gives Jev the same refreshed feed OASIS exposes to LLM agents.

The original JevFish runtime used recent SQLite posts as a cheap approximation.
OASIS LLM agents instead call SocialEnvironment.get_posts_env(), which invokes
that agent's SocialAction.refresh() and therefore uses the platform's real
recommendation buffer plus following-post logic. This adapter reuses that exact
refresh action before Jev plans behavior.

The refreshed feed is stored in a ContextVar rather than keyed by agent id. Jev
plans multiple agents concurrently with ``asyncio.gather()``, so task-local
context keeps each agent's observation isolated and avoids mismatches between
OASIS social-agent ids and runtime agent ids.
"""

from __future__ import annotations

import os
import sqlite3
from contextvars import ContextVar
from types import MethodType
from typing import Any


VALID_MODES = {"oasis_refresh", "recent"}
_CURRENT_POSTS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "jevfish_current_observation_posts",
    default=None,
)


def _author_map(db_path: str, user_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not db_path or not user_ids or not os.path.exists(db_path):
        return {}
    placeholders = ",".join("?" for _ in user_ids)
    try:
        connection = sqlite3.connect(db_path)
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT user_id, agent_id, name, user_name FROM user "
            f"WHERE user_id IN ({placeholders})",
            tuple(sorted(user_ids)),
        )
        mapping = {
            int(user_id): {
                "agent_id": int(agent_id) if agent_id is not None else None,
                "name": name,
                "user_name": user_name,
            }
            for user_id, agent_id, name, user_name in cursor.fetchall()
            if user_id is not None
        }
        connection.close()
        return mapping
    except Exception:
        return {}


def _normalize_posts(
    raw_posts: list[dict[str, Any]],
    *,
    db_path: str,
    max_posts: int,
) -> list[dict[str, Any]]:
    user_ids: set[int] = set()
    for post in raw_posts:
        try:
            if post.get("user_id") is not None:
                user_ids.add(int(post["user_id"]))
        except (TypeError, ValueError):
            pass
    authors = _author_map(db_path, user_ids)

    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for post in raw_posts:
        try:
            post_id = int(post.get("post_id"))
        except (TypeError, ValueError):
            continue
        if post_id in seen:
            continue
        seen.add(post_id)

        user_id = post.get("user_id")
        try:
            author_user_id = int(user_id) if user_id is not None else None
        except (TypeError, ValueError):
            author_user_id = None
        author = authors.get(author_user_id, {}) if author_user_id is not None else {}

        content = str(post.get("content") or "")
        quote_content = str(post.get("quote_content") or "")
        if quote_content:
            content = f"{content}\nQuoted commentary: {quote_content}".strip()

        normalized.append(
            {
                "key": f"post_{post_id}",
                "post_id": post_id,
                "content": content[:800],
                "author_user_id": author_user_id,
                "author_agent_id": author.get("agent_id"),
                "author": author.get("name") or author.get("user_name") or (
                    f"user_{author_user_id}" if author_user_id is not None else "unknown"
                ),
            }
        )
        if len(normalized) >= max_posts:
            break
    return normalized


async def _refresh_posts(
    engine: Any,
    agent: Any,
    db_path: str,
) -> list[dict[str, Any]] | None:
    env = getattr(agent, "env", None)
    action = getattr(env, "action", None)
    refresh = getattr(action, "refresh", None)
    if refresh is None:
        return None

    try:
        response = await refresh()
        engine.stats["observation_refreshes"] += 1
    except Exception as exc:
        engine.stats["observation_errors"] += 1
        print(f"[JevFish] OASIS observation refresh failed: {exc}")
        return None

    if not isinstance(response, dict) or not response.get("success"):
        engine.stats["observation_empty_refreshes"] += 1
        return []

    raw_posts = response.get("posts") or []
    if not isinstance(raw_posts, list):
        engine.stats["observation_errors"] += 1
        return None

    posts = _normalize_posts(
        [post for post in raw_posts if isinstance(post, dict)],
        db_path=db_path,
        max_posts=int(getattr(engine, "max_posts", 12)),
    )
    engine.stats["observation_posts"] += len(posts)
    if not posts:
        engine.stats["observation_empty_refreshes"] += 1
    return posts


def install_oasis_observations(engine: Any) -> Any:
    """Install personalized OASIS post-feed observations on a JevDecisionEngine."""
    mode = os.getenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh").strip().lower()
    if mode not in VALID_MODES:
        print(
            f"[JevFish] unknown observation mode {mode!r}; using oasis_refresh"
        )
        mode = "oasis_refresh"

    engine.observation_mode = mode
    engine.stats.setdefault("observation_refreshes", 0)
    engine.stats.setdefault("observation_posts", 0)
    engine.stats.setdefault("observation_empty_refreshes", 0)
    engine.stats.setdefault("observation_fallbacks", 0)
    engine.stats.setdefault("observation_errors", 0)
    engine.stats["observation_mode"] = mode

    # ``llm`` must remain the untouched upstream baseline. OASIS will perform
    # its own refresh while constructing the LLM observation/prompt.
    if getattr(engine, "mode", None) == "llm":
        engine.stats["observation_mode"] = "upstream_llm"
        print("[JevFish] observation adapter bypassed for exact LLM baseline")
        return engine

    if mode == "recent":
        print("[JevFish] observation mode=recent (legacy SQLite approximation)")
        return engine

    original_recent_posts = engine._recent_posts
    original_decide = engine.decide
    original_decide_bundle = engine.decide_bundle
    original_multi_questions = getattr(engine, "_multi_questions", None)

    def _recent_posts(self: Any, db_path: str, aid: int) -> list[dict[str, Any]]:
        del aid  # The observation is task-local; runtime/social ids need not match.
        current = _CURRENT_POSTS.get()
        if current is not None:
            return current
        self.stats["observation_fallbacks"] += 1
        return original_recent_posts(db_path, -1)

    def _multi_questions(
        self: Any,
        Choice: Any,
        *,
        platform: str,
        posts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if original_multi_questions is None:
            return {}
        questions = dict(
            original_multi_questions(
                Choice,
                platform=platform,
                posts=posts,
            )
        )
        # ``refresh()`` has already been executed to construct the observation,
        # matching OASIS's pre-LLM prompt path. Asking Jev to choose REFRESH again
        # would create a duplicate observation/tool action in the same tick.
        questions.pop("refresh", None)
        return questions

    async def _with_observation(
        self: Any,
        original: Any,
        agent: Any,
        db_path: str,
        platform: str,
    ) -> Any:
        refreshed = await _refresh_posts(self, agent, db_path)
        token = None
        if refreshed is not None:
            token = _CURRENT_POSTS.set(refreshed)
        try:
            return await original(
                agent,
                db_path=db_path,
                platform=platform,
            )
        finally:
            if token is not None:
                _CURRENT_POSTS.reset(token)

    async def decide(
        self: Any,
        agent: Any,
        *,
        db_path: str,
        platform: str,
    ) -> Any:
        return await _with_observation(
            self,
            original_decide,
            agent,
            db_path,
            platform,
        )

    async def decide_bundle(
        self: Any,
        agent: Any,
        *,
        db_path: str,
        platform: str,
    ) -> Any:
        return await _with_observation(
            self,
            original_decide_bundle,
            agent,
            db_path,
            platform,
        )

    engine._recent_posts = MethodType(_recent_posts, engine)
    if original_multi_questions is not None:
        engine._multi_questions = MethodType(_multi_questions, engine)
    engine.decide = MethodType(decide, engine)
    engine.decide_bundle = MethodType(decide_bundle, engine)
    print("[JevFish] observation mode=oasis_refresh (personalized OASIS post feed)")
    return engine
