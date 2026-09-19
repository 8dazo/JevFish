import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "jevfish_system_two.py"
spec = importlib.util.spec_from_file_location("jevfish_system_two", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def completion(text, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ]
    )


class Engine:
    def __init__(self, responses):
        self.llm_model = "meta/muse-spark-1.3-contributor"
        self.llm_base_url = "https://openrouter.ai/api/v1"
        self.client = FakeClient(responses)
        self.stats = {
            "system_two_calls": 0,
            "system_two_errors": 0,
            "system_two_by_type": {},
        }

    async def _ensure_llm_client(self):
        return self.client

    def _persona(self, agent):
        return {"persona": "skeptical engineer"}


def test_empty_reasoning_response_retries_with_larger_budget():
    engine = Engine(
        [
            completion("", finish_reason="length"),
            completion("The benchmark needs a real baseline."),
        ]
    )
    module.install_system_two_retry(engine)

    text = asyncio.run(
        engine._generate_text(
            kind="quote",
            agent=object(),
            platform="twitter",
            posts=[{"author": "Asha", "content": "New benchmark"}],
            target={"author": "Asha", "content": "New benchmark"},
        )
    )

    assert text == "The benchmark needs a real baseline."
    assert [
        request["max_tokens"]
        for request in engine.client.chat.completions.requests
    ] == [512, 1024]
    assert engine.stats["system_two_requests"] == 2
    assert engine.stats["system_two_retries"] == 1
    assert engine.stats["system_two_empty_responses"] == 1
    assert engine.stats["system_two_calls"] == 1
    assert engine.stats["system_two_errors"] == 0
    assert engine.stats["system_two_by_type"] == {"quote": 1}


def test_two_failed_attempts_are_recorded_once_as_failed_materialization():
    engine = Engine(
        [
            completion("", finish_reason="length"),
            RuntimeError("provider unavailable"),
        ]
    )
    module.install_system_two_retry(engine)

    text = asyncio.run(
        engine._generate_text(
            kind="create_post",
            agent=object(),
            platform="twitter",
            posts=[],
        )
    )

    assert text is None
    assert engine.stats["system_two_requests"] == 2
    assert engine.stats["system_two_retries"] == 1
    assert engine.stats["system_two_empty_responses"] == 1
    assert engine.stats["system_two_calls"] == 0
    assert engine.stats["system_two_errors"] == 1
