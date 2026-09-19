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
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def refresh(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class FakeEnv:
    def __init__(self, action):
        self.action = action


class FakeAgent:
    def __init__(self, agent_id, action):
        self.social_agent_id = agent_id
        self.env = FakeEnv(action)


class FakeEngine:
    def __init__(self):
        self.max_posts = 12
        self.stats = {}

    def _recent_posts(self, db_path, aid):
        return [
            {
                "key": "post_999",
                "post_id": 999,
                "content": "legacy recent post",
                "author_user_id": 9,
                "author_agent_id": 9,
                "author": "Legacy",
            }
        ]

    async def decide(self, agent, *, db_path, platform):
        return self._recent_posts(db_path, agent.social_agent_id)

    async def decide_bundle(self, agent, *, db_path, platform):
        return self._recent_posts(db_path, agent.social_agent_id)


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


def test_oasis_refresh_feed_replaces_global_recent_posts(monkeypatch, tmp_path):
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


def test_recent_mode_preserves_legacy_observation(monkeypatch):
    monkeypatch.setenv("JEVFISH_OBSERVATION_MODE", "recent")
    action = FakeAction({"success": True, "posts": []})
    agent = FakeAgent(2, action)
    engine = observation.install_oasis_observations(FakeEngine())

    posts = _run_bundle(engine, agent, "missing.db")

    assert action.calls == 0
    assert posts[0]["post_id"] == 999
    assert engine.stats["observation_mode"] == "recent"


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
    assert engine.stats["observation_errors"] == 1
    assert engine.stats["observation_fallbacks"] == 1
