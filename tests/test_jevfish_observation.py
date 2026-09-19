import asyncio
import importlib.util
import sqlite3
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "jevfish_observation.py"
spec = importlib.util.spec_from_file_location("jevfish_observation", MODULE_PATH)
observation = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(observation)


class FakeAction:
    def __init__(self, response=None, error=None, delay=0.0):
        self.response = response
        self.error = error
        self.delay = delay
        self.calls = 0

    async def refresh(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response


class FakeEnv:
    def __init__(self, action):
        self.action = action


class FakeAgent:
    def __init__(self, agent_id, action):
        # Deliberately expose a social id that differs from the id used by the
        # fake runtime lookup. This reproduces the production mismatch that the
        # old dictionary cache could not handle.
        self.social_agent_id = agent_id
        self.runtime_lookup_id = agent_id + 1000
        self.env = FakeEnv(action)


class FakeEngine:
    def __init__(self, mode="hybrid"):
        self.mode = mode
        self.max_posts = 12
        self.stats = {}

    def _recent_posts(self, db_path, aid):
        return [
            {
                "key": "post_999",
                "post_id": 999,
                "content": f"legacy recent post for {aid}",
                "author_user_id": 9,
                "author_agent_id": 9,
                "author": "Legacy",
            }
        ]

    def _multi_questions(self, Choice, *, platform, posts):
        return {"refresh": object(), "like": object()}

    async def decide(self, agent, *, db_path, platform):
        return self._recent_posts(db_path, agent.runtime_lookup_id)

    async def decide_bundle(self, agent, *, db_path, platform):
        return self._recent_posts(db_path, agent.runtime_lookup_id)


def _run_bundle(engine, agent, db_path):
    return asyncio.run(
        engine.decide_bundle(
            agent,
            db_path=db_path,
            platform="twitter",
        )
    )


def _db(tmp_path):
    path = tmp_path / "simulation.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE user (user_id INTEGER, agent_id INTEGER, name TEXT, user_name TEXT)"
    )
    connection.execute(
        "INSERT INTO user VALUES (7, 4, 'Asha', 'asha_4')"
    )
    connection.commit()
    connection.close()
    return str(path)


def test_oasis_refresh_feed_replaces_global_recent_posts_even_when_ids_differ(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh")
    action = FakeAction(
        {
            "success": True,
            "posts": [
                {
                    "post_id": 12,
                    "user_id": 7,
                    "content": "Personalized recommendation",
                    "quote_content": "Useful context",
                }
            ],
        }
    )
    agent = FakeAgent(2, action)
    engine = observation.install_oasis_observations(FakeEngine())

    posts = _run_bundle(engine, agent, _db(tmp_path))

    assert action.calls == 1
    assert [post["post_id"] for post in posts] == [12]
    assert posts[0]["author"] == "Asha"
    assert posts[0]["author_agent_id"] == 4
    assert "Useful context" in posts[0]["content"]
    assert engine.stats["observation_refreshes"] == 1
    assert engine.stats["observation_posts"] == 1
    assert engine.stats["observation_fallbacks"] == 0


def test_concurrent_agents_keep_personalized_feeds_task_local(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh")
    first = FakeAgent(
        1,
        FakeAction(
            {
                "success": True,
                "posts": [{"post_id": 101, "content": "feed one"}],
            },
            delay=0.01,
        ),
    )
    second = FakeAgent(
        2,
        FakeAction(
            {
                "success": True,
                "posts": [{"post_id": 202, "content": "feed two"}],
            }
        ),
    )
    engine = observation.install_oasis_observations(FakeEngine())

    async def run_both():
        return await asyncio.gather(
            engine.decide_bundle(first, db_path="missing.db", platform="twitter"),
            engine.decide_bundle(second, db_path="missing.db", platform="twitter"),
        )

    first_posts, second_posts = asyncio.run(run_both())

    assert [post["post_id"] for post in first_posts] == [101]
    assert [post["post_id"] for post in second_posts] == [202]
    assert engine.stats["observation_refreshes"] == 2
    assert engine.stats["observation_fallbacks"] == 0


def test_exact_feed_mode_removes_duplicate_refresh_question(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh")
    engine = observation.install_oasis_observations(FakeEngine())

    questions = engine._multi_questions(
        object,
        platform="twitter",
        posts=[],
    )

    assert "refresh" not in questions
    assert "like" in questions


def test_llm_mode_bypasses_jevfish_observation_adapter(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh")
    action = FakeAction(
        {
            "success": True,
            "posts": [{"post_id": 12, "content": "should not be pre-refreshed"}],
        }
    )
    agent = FakeAgent(2, action)
    engine = observation.install_oasis_observations(FakeEngine(mode="llm"))

    posts = _run_bundle(engine, agent, "missing.db")

    assert action.calls == 0
    assert posts[0]["post_id"] == 999
    assert engine.stats["observation_mode"] == "upstream_llm"
    assert engine.stats["observation_refreshes"] == 0


def test_recent_mode_preserves_legacy_observation_and_refresh_gate(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "recent")
    action = FakeAction({"success": True, "posts": []})
    agent = FakeAgent(2, action)
    engine = observation.install_oasis_observations(FakeEngine())

    posts = _run_bundle(engine, agent, "missing.db")
    questions = engine._multi_questions(object, platform="twitter", posts=[])

    assert action.calls == 0
    assert posts[0]["post_id"] == 999
    assert engine.stats["observation_mode"] == "recent"
    assert "refresh" in questions


def test_empty_refresh_is_preserved_as_empty_feed(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh")
    action = FakeAction({"success": False, "message": "No posts found."})
    agent = FakeAgent(2, action)
    engine = observation.install_oasis_observations(FakeEngine())

    posts = _run_bundle(engine, agent, "missing.db")

    assert posts == []
    assert engine.stats["observation_empty_refreshes"] == 1
    assert engine.stats["observation_fallbacks"] == 0


def test_refresh_error_falls_back_to_recent_posts(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "oasis_refresh")
    action = FakeAction(error=RuntimeError("channel unavailable"))
    agent = FakeAgent(2, action)
    engine = observation.install_oasis_observations(FakeEngine())

    posts = _run_bundle(engine, agent, "missing.db")

    assert posts[0]["post_id"] == 999
    assert str(agent.runtime_lookup_id) in posts[0]["content"]
    assert engine.stats["observation_errors"] == 1
    assert engine.stats["observation_fallbacks"] == 1
