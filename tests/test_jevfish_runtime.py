import asyncio
import importlib.util
import os
import sqlite3
import sys
import tempfile
import types
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


RUNTIME_PATH = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "jevfish_runtime.py"
spec = importlib.util.spec_from_file_location("jevfish_runtime", RUNTIME_PATH)
runtime = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runtime)


class ActionType(Enum):
    DO_NOTHING = "do_nothing"
    LIKE_POST = "like_post"
    REPOST = "repost"
    DISLIKE_POST = "dislike_post"
    FOLLOW = "follow"


class LLMAction:
    pass


@dataclass
class ManualAction:
    action_type: ActionType
    action_args: dict


class Legacy:
    ActionType = ActionType
    LLMAction = LLMAction
    ManualAction = ManualAction


class Agent:
    def __init__(self, agent_id: int):
        self.agent_id = agent_id


class Answer:
    def __init__(self, choice, confidence, probabilities):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = probabilities


class Response:
    def __init__(self, action: Answer, target: Answer):
        self.choices = {"action": action, "target": target}


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def system_one(self, **kwargs):
        return self.response

    async def aclose(self):
        return None


def _install_fake_typesafe_module():
    fake = types.ModuleType("typesafe_sdk")

    class Choice:
        def __init__(self, instructions=None, criteria=None):
            self.instructions = instructions
            self.criteria = criteria

    fake.Choice = Choice
    sys.modules["typesafe_sdk"] = fake


def _create_social_db(path: str):
    connection = sqlite3.connect(path)
    cursor = connection.cursor()
    cursor.execute(
        "CREATE TABLE user (user_id INTEGER PRIMARY KEY, agent_id INTEGER, name TEXT, user_name TEXT)"
    )
    cursor.execute(
        "CREATE TABLE post (post_id INTEGER PRIMARY KEY, content TEXT, user_id INTEGER)"
    )
    cursor.execute(
        "INSERT INTO user(user_id, agent_id, name, user_name) VALUES (10, 2, 'Alice', 'alice')"
    )
    cursor.execute(
        "INSERT INTO post(post_id, content, user_id) VALUES (7, 'A new open model just launched', 10)"
    )
    connection.commit()
    connection.close()


def _engine(response):
    engine = runtime.JevDecisionEngine(Legacy, {"agent_configs": [{"agent_id": 1, "persona": "developer"}]})
    engine.mode = "hybrid"
    engine.api_key = "test-key"
    engine.sample_probabilities = False
    engine._client = FakeClient(response)
    return engine


def test_jev_can_replace_llm_action_with_direct_like():
    _install_fake_typesafe_module()
    response = Response(
        Answer("like_post", 0.95, {"like_post": 0.95, "do_nothing": 0.05}),
        Answer("post_7", 0.98, {"post_7": 0.98, "none": 0.02}),
    )
    engine = _engine(response)

    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        action = asyncio.run(engine.decide(Agent(1), db_path=db_path, platform="twitter"))

    assert isinstance(action, ManualAction)
    assert action.action_type is ActionType.LIKE_POST
    assert action.action_args == {"post_id": 7}
    assert engine.stats["jev_manual_actions"] == 1
    assert engine.stats["llm_fallbacks"] == 0


def test_low_confidence_routes_back_to_system_two_llm():
    _install_fake_typesafe_module()
    response = Response(
        Answer("like_post", 0.51, {"like_post": 0.51, "do_nothing": 0.49}),
        Answer("post_7", 0.90, {"post_7": 0.90, "none": 0.10}),
    )
    engine = _engine(response)

    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        action = asyncio.run(engine.decide(Agent(1), db_path=db_path, platform="twitter"))

    assert isinstance(action, LLMAction)
    assert engine.stats["llm_fallbacks"] == 1


def test_follow_maps_selected_post_author_to_followee_id():
    _install_fake_typesafe_module()
    response = Response(
        Answer("follow_author", 0.91, {"follow_author": 0.91, "do_nothing": 0.09}),
        Answer("post_7", 0.94, {"post_7": 0.94, "none": 0.06}),
    )
    engine = _engine(response)

    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        action = asyncio.run(engine.decide(Agent(1), db_path=db_path, platform="twitter"))

    assert isinstance(action, ManualAction)
    assert action.action_type is ActionType.FOLLOW
    assert action.action_args == {"followee_id": 10}


def test_llm_mode_is_exact_baseline_passthrough():
    engine = runtime.JevDecisionEngine(Legacy, {})
    engine.mode = "llm"
    action = asyncio.run(engine.decide(Agent(1), db_path="missing.db", platform="twitter"))

    assert isinstance(action, LLMAction)
    assert engine.stats["llm_fallbacks"] == 1
