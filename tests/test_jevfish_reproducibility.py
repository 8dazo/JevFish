import importlib.util
import random
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "jevfish_reproducibility.py"
spec = importlib.util.spec_from_file_location("jevfish_reproducibility", MODULE_PATH)
repro = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(repro)


class Engine:
    def __init__(self):
        self.stats = {}


def test_missing_seed_is_disabled(monkeypatch):
    monkeypatch.delenv("JEVFISH_SEED", raising=False)
    engine = Engine()
    assert repro.apply_reproducibility(engine) is None
    assert engine.stats["seed"] is None


def test_integer_seed_repeats_python_random_stream(monkeypatch):
    monkeypatch.setenv("JEVFISH_SEED", "42")
    first_engine = Engine()
    assert repro.apply_reproducibility(first_engine) == 42
    first = [random.random() for _ in range(4)]

    second_engine = Engine()
    assert repro.apply_reproducibility(second_engine) == 42
    second = [random.random() for _ in range(4)]

    assert first == second
    assert second_engine.stats["seed"] == 42


def test_text_seed_is_stable(monkeypatch):
    monkeypatch.setenv("JEVFISH_SEED", "jevfish-benchmark")
    a = repro.apply_reproducibility(Engine())
    b = repro.apply_reproducibility(Engine())
    assert isinstance(a, int)
    assert a == b
