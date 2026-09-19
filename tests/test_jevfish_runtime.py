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
    REFRESH = "refresh"
    CREATE_POST = "create_post"
    QUOTE_POST = "quote_post"
    CREATE_COMMENT = "create_comment"


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
    def __init__(self, action=None, target=None, *, choices=None):
        if choices is not None:
            self.choices = choices
        else:
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
    engine = runtime.JevDecisionEngine(
        Legacy,
        {"agent_configs": [{"agent_id": 1, "persona": "developer"}]},
    )
    engine.mode = "hybrid"
    engine.policy_mode = "multi"
    engine.api_key = "test-key"
    engine.threshold = 0.58
    engine.sample_probabilities = False
    engine._client = FakeClient(response)
    return engine


def _yes(confidence=0.95):
    return Answer("yes", confidence, {"yes": confidence, "no": 1 - confidence})


def _no(confidence=0.95):
    return Answer("no", confidence, {"yes": 1 - confidence, "no": confidence})


def _target(post_id=7, confidence=0.96):
    key = f"post_{post_id}"
    return Answer(key, confidence, {key: confidence, "none": 1 - confidence})


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
        action = asyncio.run(
            engine.decide(Agent(1), db_path=db_path, platform="twitter")
        )

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
        action = asyncio.run(
            engine.decide(Agent(1), db_path=db_path, platform="twitter")
        )

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
        action = asyncio.run(
            engine.decide(Agent(1), db_path=db_path, platform="twitter")
        )

    assert isinstance(action, ManualAction)
    assert action.action_type is ActionType.FOLLOW
    assert action.action_args == {"followee_id": 10}


def test_llm_mode_is_exact_baseline_passthrough():
    engine = runtime.JevDecisionEngine(Legacy, {})
    engine.mode = "llm"
    action = asyncio.run(
        engine.decide(Agent(1), db_path="missing.db", platform="twitter")
    )

    assert isinstance(action, LLMAction)
    assert engine.stats["llm_fallbacks"] == 1


def test_multi_policy_emits_multiple_targeted_actions_from_one_jev_plan():
    _install_fake_typesafe_module()
    response = Response(
        choices={
            "refresh": _no(),
            "like": _yes(0.96),
            "like_target": _target(confidence=0.98),
            "follow": _yes(0.91),
            "follow_target": _target(confidence=0.95),
            "repost": _yes(0.89),
            "repost_target": _target(confidence=0.93),
            "quote": _no(),
            "quote_target": _target(),
            "create_post": _no(),
        }
    )
    engine = _engine(response)
    engine.max_actions = 3

    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        actions = asyncio.run(
            engine.decide_bundle(Agent(1), db_path=db_path, platform="twitter")
        )

    assert isinstance(actions, list)
    assert len(actions) == 3
    assert {action.action_type for action in actions} == {
        ActionType.LIKE_POST,
        ActionType.FOLLOW,
        ActionType.REPOST,
    }
    assert all(isinstance(action, ManualAction) for action in actions)
    assert engine.stats["jev_calls"] == 1
    assert engine.stats["jev_plans"] == 1
    assert engine.stats["multi_action_agents"] == 1
    assert engine.stats["jev_manual_actions"] == 3
    assert engine.stats["llm_fallbacks"] == 0


def test_multi_policy_materializes_language_after_jev_selects_create_post():
    _install_fake_typesafe_module()
    response = Response(
        choices={
            "refresh": _no(),
            "like": _no(),
            "like_target": _target(),
            "follow": _no(),
            "follow_target": _target(),
            "repost": _no(),
            "repost_target": _target(),
            "quote": _no(),
            "quote_target": _target(),
            "create_post": _yes(0.97),
        }
    )
    engine = _engine(response)

    async def fake_generate_text(**kwargs):
        return "Benchmarks first; claims second."

    engine._generate_text = fake_generate_text

    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        actions = asyncio.run(
            engine.decide_bundle(Agent(1), db_path=db_path, platform="twitter")
        )

    assert isinstance(actions, list)
    assert len(actions) == 1
    assert actions[0].action_type is ActionType.CREATE_POST
    assert actions[0].action_args == {"content": "Benchmarks first; claims second."}
    assert engine.stats["llm_fallbacks"] == 0
    assert engine.stats["selected_by_type"]["create_post"] == 1


def test_multi_policy_uses_llm_only_when_all_selected_behavior_is_uncertain():
    _install_fake_typesafe_module()
    response = Response(
        choices={
            "refresh": _no(),
            "like": _yes(0.54),
            "like_target": _target(confidence=0.99),
            "follow": _no(),
            "follow_target": _target(),
            "repost": _no(),
            "repost_target": _target(),
            "quote": _no(),
            "quote_target": _target(),
            "create_post": _no(),
        }
    )
    engine = _engine(response)

    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        action = asyncio.run(
            engine.decide_bundle(Agent(1), db_path=db_path, platform="twitter")
        )

    assert isinstance(action, LLMAction)
    assert engine.stats["uncertain_gates"] >= 1
    assert engine.stats["llm_escalations"] == 1


def test_transform_actions_uses_multi_policy_bundles_by_default():
    _install_fake_typesafe_module()
    response = Response(
        choices={
            "refresh": _no(),
            "like": _yes(0.96),
            "like_target": _target(),
            "follow": _no(),
            "follow_target": _target(),
            "repost": _yes(0.90),
            "repost_target": _target(),
            "quote": _no(),
            "quote_target": _target(),
            "create_post": _no(),
        }
    )
    engine = _engine(response)

    agent = Agent(1)
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "sim.db")
        _create_social_db(db_path)
        transformed = asyncio.run(
            engine.transform_actions(
                {agent: LLMAction()},
                db_path=db_path,
                platform="twitter",
            )
        )

    assert isinstance(transformed[agent], list)
    assert len(transformed[agent]) == 2
    assert engine.stats["multi_action_agents"] == 1
