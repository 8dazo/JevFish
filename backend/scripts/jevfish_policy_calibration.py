"""Adaptive confidence thresholds for JevFish V0.3.

A single global confidence threshold forces an unnecessary trade-off: raising it
reduces System-Two calls but also suppresses cheap social behavior such as
follows and reposts. This adapter keeps cheap actions expressive while requiring
higher confidence for language-heavy actions.
"""

from __future__ import annotations

import os
from types import MethodType
from typing import Any, Optional


GENERATIVE_ACTIONS = {"quote", "create_post", "comment"}


def _threshold_env(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return max(0.0, min(1.0, float(fallback)))
    try:
        value = float(raw)
    except ValueError:
        value = float(fallback)
    return max(0.0, min(1.0, value))


def install_adaptive_thresholds(engine: Any) -> Any:
    """Patch one JevDecisionEngine instance with per-action thresholds."""
    base = float(getattr(engine, "threshold", 0.58))
    generative = _threshold_env(
        "JEVFISH_GENERATIVE_CONFIDENCE_THRESHOLD",
        max(base, 0.72),
    )
    target = _threshold_env("JEVFISH_TARGET_CONFIDENCE_THRESHOLD", base)

    defaults = {
        "refresh": max(0.50, base - 0.05),
        "like": base,
        "follow": base,
        "repost": max(base, 0.60),
        "dislike": max(base, 0.60),
        "quote": generative,
        "create_post": generative,
        "comment": generative,
    }
    thresholds = {
        action: _threshold_env(
            f"JEVFISH_{action.upper()}_CONFIDENCE_THRESHOLD",
            default,
        )
        for action, default in defaults.items()
    }

    engine.action_thresholds = thresholds
    engine.target_threshold = target
    engine.generative_threshold = generative
    engine.stats["confidence_thresholds"] = {
        **thresholds,
        "target": target,
    }

    def _selected_gate(
        self: Any,
        response: Any,
        name: str,
    ) -> tuple[bool, float, bool]:
        answer = response.choices.get(name)
        if answer is None:
            return False, 0.0, False
        choice, confidence = self._choose(answer)
        if choice != "yes":
            return False, confidence, False

        threshold = float(self.action_thresholds.get(name, self.threshold))
        if confidence < threshold:
            self.stats["uncertain_gates"] += 1
            return False, confidence, True
        return True, confidence, False

    def _candidate_with_target(
        self: Any,
        response: Any,
        gate_name: str,
        target_name: str,
        posts: list[dict[str, Any]],
    ) -> tuple[Optional[dict[str, Any]], bool]:
        selected, gate_confidence, uncertain = self._selected_gate(
            response,
            gate_name,
        )
        if not selected:
            return None, uncertain

        target_answer = response.choices.get(target_name)
        if target_answer is None:
            return None, True

        target_item, target_confidence = self._target_from_answer(
            target_answer,
            posts,
        )
        if target_item is None or target_confidence < self.target_threshold:
            self.stats["uncertain_gates"] += 1
            return None, True

        return {
            "name": gate_name,
            "score": min(gate_confidence, target_confidence),
            "target": target_item,
        }, uncertain

    engine._selected_gate = MethodType(_selected_gate, engine)
    engine._candidate_with_target = MethodType(_candidate_with_target, engine)

    print(
        "[JevFish] adaptive thresholds: "
        + ", ".join(
            f"{name}={value:.2f}"
            for name, value in thresholds.items()
        )
        + f", target={target:.2f}"
    )
    return engine
