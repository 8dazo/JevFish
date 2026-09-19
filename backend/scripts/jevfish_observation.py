"""Observation adapter that gives Jev the same refreshed feed OASIS exposes to LLM agents.

The original JevFish runtime used recent SQLite posts as a cheap approximation.
OASIS LLM agents instead call SocialEnvironment.get_posts_env(), which invokes
that agent's SocialAction.refresh() and therefore uses the platform's real
recommendation buffer plus following-post logic. This adapter reuses that exact
refresh action before Jev plans behavior.
"""

from __future__ import annotations

import os
import sqlite3
from types import MethodType
from typing import Any


VALID_MODES = {"oasis_refresh", "recent"}


def _agent_id(agent: Any) -> int:
    for name in ("social_agent_id", "agent_id", "id"):
        value = getattr(agent, name, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return -1


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

    if mode == "recent":
        print("[JevFish] observation mode=recent (legacy SQLite approximation)")
        return engine

    original_recent_posts = engine._recent_posts
    original_decide = engine.decide
    original_decide_bundle = engine.decide_bundle
    cache: dict[int, list[dict[str, Any]]] = {}

    def _recent_posts(self: Any, db_path: str, aid: int) -> list[dict[str, Any]]:
        if aid in cache:
            return cache[aid]
        self.stats["observation_fallbacks"] += 1
        return original_recent_posts(db_path, aid)

    async def _with_observation(
        self: Any,
        original: Any,
        agent: Any,
        db_path: str,
        platform: str,
    ) -> Any:
        aid = _agent_id(agent)
        refreshed = await _refresh_posts(self, agent, db_path)
        if refreshed is not None:
            cache[aid] = refreshed
        try:
            # JevDecisionEngine keeps db_path/platform keyword-only. Preserving
            # that contract matters because these are saved bound methods.
            return await original(
                agent,
                db_path=db_path,
                platform=platform,
            )
        finally:
            cache.pop(aid, None)

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
    engine.decide = MethodType(decide, engine)
    engine.decide_bundle = MethodType(decide_bundle, engine)
    print("[JevFish] observation mode=oasis_refresh (personalized OASIS post feed)")
    return engine
