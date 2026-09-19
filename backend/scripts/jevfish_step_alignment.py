"""Align JevFish observation timing with OASIS ``OasisEnv.step``.

OASIS updates its recommendation table at the beginning of every step and only
then lets LLM agents refresh/read their feed. JevFish transforms ``LLMAction``
objects before calling the wrapped ``env.step()``, so a personalized refresh
performed during that transform would otherwise run against the previous/empty
recommendation table.

This adapter performs the same recommendation update immediately before Jev
plans the step, then suppresses only OASIS's duplicate update for that one
wrapped call. ``llm`` mode is never touched and therefore remains an exact
upstream baseline.
"""

from __future__ import annotations

from typing import Any


def install_step_alignment(engine: Any, proxy_cls: Any = None) -> Any:
    """Patch JevEnvironmentProxy.step to match OASIS recommendation ordering."""
    if proxy_cls is None:
        from jevfish_runtime import JevEnvironmentProxy

        proxy_cls = JevEnvironmentProxy

    if getattr(proxy_cls, "_jevfish_step_alignment_installed", False):
        return engine

    original_step = proxy_cls.step
    engine.stats.setdefault("observation_rec_updates", 0)
    engine.stats.setdefault("observation_rec_update_errors", 0)

    async def step(self: Any, actions: Any) -> Any:
        current_engine = self._engine
        exact_observation = (
            getattr(current_engine, "mode", None) != "llm"
            and getattr(current_engine, "observation_mode", None)
            == "oasis_refresh"
        )
        if not exact_observation:
            return await original_step(self, actions)

        env = self._env
        platform = getattr(env, "platform", None)
        updater = getattr(platform, "update_rec_table", None)
        if updater is None:
            current_engine.stats["observation_rec_update_errors"] += 1
            return await original_step(self, actions)

        try:
            # Match the first line of OASIS OasisEnv.step(). Jev's subsequent
            # refresh therefore reads the same recommendation state an LLM turn
            # would see.
            await updater()
            current_engine.stats["observation_rec_updates"] += 1
        except Exception as exc:
            current_engine.stats["observation_rec_update_errors"] += 1
            print(f"[JevFish] recommendation pre-update failed: {exc}")
            # Let upstream OASIS own the step normally if preparation fails.
            return await original_step(self, actions)

        transformed = await current_engine.transform_actions(
            actions,
            db_path=self._db_path,
            platform=self._platform,
        )

        async def _already_updated() -> None:
            return None

        # OASIS would call update_rec_table() again at the beginning of step().
        # Suppress exactly that duplicate call, then restore the bound method.
        platform.update_rec_table = _already_updated
        try:
            return await env.step(transformed)
        finally:
            platform.update_rec_table = updater

    proxy_cls.step = step
    proxy_cls._jevfish_step_alignment_installed = True
    print("[JevFish] step alignment=OASIS recsys update before Jev observation")
    return engine
