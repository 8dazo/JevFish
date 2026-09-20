"""Persist JevFish routing metrics while a simulation is still running.

The base runtime writes its final metrics when an OASIS environment closes. A
public demo needs those counters during the run, so this tiny adapter snapshots
the same payload after each successful environment step without changing OASIS
behavior.
"""

from __future__ import annotations

from typing import Any

from jevfish_runtime import JevEnvironmentProxy


_INSTALLED = False


def install_live_metrics() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_step = JevEnvironmentProxy.step

    async def step_with_metrics(self: JevEnvironmentProxy, actions: Any) -> Any:
        result = await original_step(self, actions)
        self._write_metrics()
        return result

    JevEnvironmentProxy.step = step_with_metrics
    _INSTALLED = True
