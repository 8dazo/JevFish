import asyncio
import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "scripts"
    / "jevfish_step_alignment.py"
)
spec = importlib.util.spec_from_file_location("jevfish_step_alignment", MODULE_PATH)
alignment = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(alignment)


class FakePlatform:
    def __init__(self):
        self.updates = 0

    async def update_rec_table(self):
        self.updates += 1


class FakeEnv:
    def __init__(self, platform):
        self.platform = platform
        self.step_calls = 0
        self.received = None

    async def step(self, actions):
        # Mirrors OASIS: recommendation update is the first operation in step.
        await self.platform.update_rec_table()
        self.step_calls += 1
        self.received = actions
        return "done"


class FakeEngine:
    def __init__(self, platform, mode="hybrid", observation_mode="oasis_refresh"):
        self.platform = platform
        self.mode = mode
        self.observation_mode = observation_mode
        self.stats = {}
        self.updates_seen_while_transforming = None

    async def transform_actions(self, actions, *, db_path, platform):
        self.updates_seen_while_transforming = self.platform.updates
        return {"transformed": actions, "db_path": db_path, "platform": platform}


class FakeProxy:
    _jevfish_step_alignment_installed = False

    def __init__(self, env, engine):
        self._env = env
        self._engine = engine
        self._db_path = "simulation.db"
        self._platform = "twitter"

    async def step(self, actions):
        transformed = await self._engine.transform_actions(
            actions,
            db_path=self._db_path,
            platform=self._platform,
        )
        return await self._env.step(transformed)


def _proxy_class():
    # Each test gets a fresh class so the class-level idempotency marker does
    # not leak between tests.
    class Proxy(FakeProxy):
        _jevfish_step_alignment_installed = False

    return Proxy


def test_hybrid_updates_recs_before_transform_and_only_once():
    platform = FakePlatform()
    env = FakeEnv(platform)
    engine = FakeEngine(platform)
    proxy_cls = _proxy_class()
    alignment.install_step_alignment(engine, proxy_cls)
    proxy = proxy_cls(env, engine)

    result = asyncio.run(proxy.step({"agent": "llm-action"}))

    assert result == "done"
    assert engine.updates_seen_while_transforming == 1
    assert platform.updates == 1
    assert env.step_calls == 1
    assert engine.stats["observation_rec_updates"] == 1
    assert engine.stats["observation_rec_update_errors"] == 0
    assert env.received["transformed"] == {"agent": "llm-action"}


def test_llm_mode_preserves_unmodified_upstream_step_order():
    platform = FakePlatform()
    env = FakeEnv(platform)
    engine = FakeEngine(platform, mode="llm")
    proxy_cls = _proxy_class()
    alignment.install_step_alignment(engine, proxy_cls)
    proxy = proxy_cls(env, engine)

    asyncio.run(proxy.step({"agent": "llm-action"}))

    # In the baseline, transform happens before OASIS updates recommendations,
    # exactly as the original JevEnvironmentProxy / OasisEnv combination does.
    assert engine.updates_seen_while_transforming == 0
    assert platform.updates == 1
    assert engine.stats["observation_rec_updates"] == 0


def test_recent_observation_mode_preserves_upstream_step_order():
    platform = FakePlatform()
    env = FakeEnv(platform)
    engine = FakeEngine(platform, observation_mode="recent")
    proxy_cls = _proxy_class()
    alignment.install_step_alignment(engine, proxy_cls)
    proxy = proxy_cls(env, engine)

    asyncio.run(proxy.step({"agent": "llm-action"}))

    assert engine.updates_seen_while_transforming == 0
    assert platform.updates == 1
    assert engine.stats["observation_rec_updates"] == 0
