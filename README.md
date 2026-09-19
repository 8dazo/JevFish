# JevFish

**JevFish is a System-One swarm simulation engine built on MiroFish + OASIS + TypeSafe Jev.**

Instead of asking a generative LLM to make every tiny social decision, JevFish splits the simulation into two layers:

- **Jev / System One** handles fast bounded reactions such as ignore, like, repost, downvote, and follow.
- **The existing LLM / System Two** is used only when the agent needs original language or Jev is uncertain.

That architecture is aimed at making large stochastic population simulations much cheaper and faster, so the same initial world can eventually be rolled out into many alternative futures rather than one expensive trajectory.

> JevFish is experimental. Simulation frequencies are simulation outputs, not calibrated real-world probabilities unless separately validated against real observations.

## Architecture

```text
seed documents
     |
     v
MiroFish knowledge graph + personas
     |
     v
OASIS social world
     |
     v
active agent + recent feed
     |
     v
  TypeSafe Jev
     |
     +--> DO_NOTHING -----> OASIS ManualAction
     +--> LIKE -----------> OASIS ManualAction
     +--> REPOST ---------> OASIS ManualAction
     +--> DISLIKE --------> OASIS ManualAction
     +--> FOLLOW ---------> OASIS ManualAction
     |
     +--> GENERATE / LOW CONFIDENCE
                  |
                  v
              LLMAction()
```

The original MiroFish simulator bodies are preserved as `*_legacy.py`. The normal simulation entrypoints now install `backend/scripts/jevfish_runtime.py` and then execute the preserved implementation, so the baseline can still be reproduced.

## Decision modes

Set `JEVFISH_DECISION_ENGINE` to one of:

- `llm` — original MiroFish behavior; every upstream `LLMAction()` remains an LLM call.
- `hybrid` — recommended; Jev executes bounded decisions and the LLM handles language/uncertainty.
- `jev` — structured Jev-only stress-test mode; failed Jev decisions become no-ops rather than LLM fallbacks.

## Quick start

### Requirements

- Node.js 18+
- Python 3.11–3.12
- `uv`
- an OpenAI-compatible LLM API key for System-Two/generative actions
- a TypeSafe API key for Jev
- a Zep Cloud key for the existing graph-memory pipeline

### Configure

```bash
cp .env.example .env
```

At minimum, fill in:

```env
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_NAME=...

TYPESAFE_API_KEY=...
TYPESAFE_DEFAULT_MODEL=jev-latest
JEVFISH_DECISION_ENGINE=hybrid

ZEP_API_KEY=...
```

Useful JevFish controls:

```env
JEVFISH_CONFIDENCE_THRESHOLD=0.58
JEVFISH_MAX_CONTEXT_POSTS=12
JEVFISH_SAMPLE_PROBABILITIES=true
```

`JEVFISH_SAMPLE_PROBABILITIES=true` intentionally samples Jev's returned probability distribution instead of always taking argmax. This keeps repeated worlds stochastic rather than turning every persona into a deterministic policy.

### Install and run

```bash
npm run setup:all
npm run dev
```

Services remain compatible with the original application:

- frontend: `http://localhost:3000`
- backend: `http://localhost:5001`

## What changed from MiroFish

The first JevFish milestone is deliberately narrow:

1. the original simulation entrypoints are preserved as legacy files;
2. a runtime environment proxy intercepts upstream `LLMAction()` calls;
3. Jev receives the persona plus a compact recent-feed state;
4. Jev answers typed `Choice` questions for action + target;
5. bounded actions execute directly through OASIS `ManualAction`;
6. free-form or low-confidence decisions fall back to the original LLM;
7. each platform writes `jevfish_<platform>_metrics.json` beside its simulation database;
8. unit tests cover direct Jev actions, confidence fallback, author-follow mapping, and exact LLM baseline mode.

## Benchmark JevFish against the baseline

Run the same prepared simulation twice:

```bash
JEVFISH_DECISION_ENGINE=llm
# run simulation

JEVFISH_DECISION_ENGINE=hybrid
# run the same simulation again
```

Compare:

- wall-clock runtime;
- Jev calls;
- LLM fallbacks / LLM calls avoided;
- actions per second;
- estimated cost;
- action-type distribution;
- network evolution;
- final-report divergence;
- stability across repeated stochastic worlds.

The first serious research question is not simply whether JevFish is cheaper. It is whether fast System-One micro-agents let us run **many more independent trajectories** while retaining useful population-level behavior.

## Roadmap

- **V0.1 — Hybrid action engine:** bounded Jev reactions + System-Two fallback. *(implemented on the current development branch)*
- **V0.2 — Jev activity policy:** replace random activity scheduling with persona/time/context-conditioned decisions.
- **V0.3 — Explicit belief state:** compact per-agent beliefs and affinity updates after exposure.
- **V0.4 — Monte Carlo worlds:** fork identical initial conditions into many Jev-driven stochastic rollouts.
- **V0.5 — Intervention branches:** inject an event at time T in one branch and compare downstream outcome distributions.

See [JEVFISH.md](./JEVFISH.md) for the detailed architecture and experiment plan.

## Upstream and acknowledgements

JevFish is derived from **MiroFish** and keeps its graph construction, persona generation, dual-platform simulation, interviews, report agent, and Zep memory architecture.

- MiroFish: https://github.com/666ghj/MiroFish
- OASIS: https://github.com/camel-ai/oasis
- TypeSafe AI / Jev: https://typesafe.ai/

The original project is licensed under AGPL-3.0; JevFish keeps the repository license and upstream attribution.
