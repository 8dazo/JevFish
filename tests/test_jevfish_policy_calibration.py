import importlib.util
import os
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "jevfish_policy_calibration.py"
spec = importlib.util.spec_from_file_location("jevfish_policy_calibration", MODULE_PATH)
calibration = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(calibration)


class Answer:
    def __init__(self, choice, confidence):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = {choice: confidence}


class Response:
    def __init__(self, **choices):
        self.choices = choices


class Engine:
    def __init__(self):
        self.threshold = 0.58
        self.stats = {"uncertain_gates": 0}

    def _choose(self, answer):
        return answer.choice, answer.confidence

    def _target_from_answer(self, answer, posts):
        key = answer.choice
        target = next((post for post in posts if post["key"] == key), None)
        return target, answer.confidence

    def _selected_gate(self, response, name):
        raise AssertionError("adapter was not installed")

    def _candidate_with_target(self, response, gate_name, target_name, posts):
        raise AssertionError("adapter was not installed")


def test_cheap_actions_keep_base_threshold_while_language_is_stricter(monkeypatch):
    monkeypatch.delenv("JEVFISH_GENERATIVE_CONFIDENCE_THRESHOLD", raising=False)
    engine = calibration.install_adaptive_thresholds(Engine())

    response = Response(
        like=Answer("yes", 0.61),
        follow=Answer("yes", 0.60),
        quote=Answer("yes", 0.70),
    )

    assert engine._selected_gate(response, "like") == (True, 0.61, False)
    assert engine._selected_gate(response, "follow") == (True, 0.60, False)
    selected, confidence, uncertain = engine._selected_gate(response, "quote")
    assert selected is False
    assert confidence == 0.70
    assert uncertain is True
    assert engine.action_thresholds["quote"] == 0.72


def test_per_action_override_can_raise_or_lower_one_gate(monkeypatch):
    monkeypatch.setenv("JEVFISH_FOLLOW_CONFIDENCE_THRESHOLD", "0.75")
    monkeypatch.setenv("JEVFISH_QUOTE_CONFIDENCE_THRESHOLD", "0.68")
    engine = calibration.install_adaptive_thresholds(Engine())

    response = Response(
        follow=Answer("yes", 0.70),
        quote=Answer("yes", 0.70),
    )

    assert engine._selected_gate(response, "follow")[0] is False
    assert engine._selected_gate(response, "quote")[0] is True


def test_target_threshold_is_independent_from_generation_threshold(monkeypatch):
    monkeypatch.setenv("JEVFISH_GENERATIVE_CONFIDENCE_THRESHOLD", "0.78")
    monkeypatch.setenv("JEVFISH_TARGET_CONFIDENCE_THRESHOLD", "0.58")
    engine = calibration.install_adaptive_thresholds(Engine())
    posts = [{"key": "post_7", "post_id": 7}]
    response = Response(
        quote=Answer("yes", 0.82),
        quote_target=Answer("post_7", 0.62),
    )

    candidate, uncertain = engine._candidate_with_target(
        response,
        "quote",
        "quote_target",
        posts,
    )

    assert uncertain is False
    assert candidate is not None
    assert candidate["name"] == "quote"
    assert candidate["target"]["post_id"] == 7
    assert candidate["score"] == 0.62


def test_threshold_values_are_clamped(monkeypatch):
    monkeypatch.setenv("JEVFISH_LIKE_CONFIDENCE_THRESHOLD", "1.5")
    monkeypatch.setenv("JEVFISH_TARGET_CONFIDENCE_THRESHOLD", "-2")
    engine = calibration.install_adaptive_thresholds(Engine())

    assert engine.action_thresholds["like"] == 1.0
    assert engine.target_threshold == 0.0
