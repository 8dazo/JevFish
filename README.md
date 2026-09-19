<div align="center">

<img src="./static/image/jevfish/hero.svg" alt="JevFish — System-One swarm simulation" width="100%" />

# JevFish

### Fast micro-decisions. Many possible worlds.

[![Jev](https://img.shields.io/badge/TypeSafe-Jev-63E6FF?style=flat-square)](https://typesafe.ai/)
[![OASIS](https://img.shields.io/badge/Simulation-OASIS-7C83FF?style=flat-square)](https://github.com/camel-ai/oasis)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-D96CFF?style=flat-square)](./LICENSE)

**JevFish is an experimental hybrid swarm-simulation engine that uses TypeSafe Jev for fast System-One behavior and a generative LLM only when agents actually need language or deeper reasoning.**

</div>

Instead of spending a full generative call on every tiny social decision, JevFish separates **reaction** from **generation**:

- **Jev / System One** handles bounded decisions such as ignore, like, repost, dislike, and follow.
- **LLM / System Two** wakes up for free-form language, complex actions, or low-confidence cases.
- **OASIS** executes the social world and preserves the existing simulation mechanics.
- **The long-term goal** is to make repeated stochastic rollouts cheap enough to explore distributions of possible futures instead of producing only one expensive trajectory.

> [!IMPORTANT]
> JevFish is a simulation system, not an oracle. Frequencies observed across rollouts are **simulation frequencies**, not calibrated real-world probabilities unless they are separately validated against real observations.

## Why JevFish

A conventional LLM-agent simulation often does this for every active agent:

```text
observe world → full LLM call → choose action → execute
```

Most turns do not actually require generation. An agent may simply ignore a post, like it, repost it, dislike it, or follow someone.

JevFish instead uses:

```text
observe world
     ↓
    Jev
     ↓
fast bounded decision ──────→ execute immediately
     │
     └── language / uncertainty ─→ generative LLM
```

That makes Jev the high-frequency behavioral layer and reserves the expensive model for the smaller set of turns that benefit from System-Two generation.

## Hybrid engine

<div align="center">
<img src="./static/image/jevfish/hybrid-engine.svg" alt="JevFish hybrid System-One and System-Two engine" width="100%" />
</div>

The current runtime intercepts upstream `LLMAction()` requests at the OASIS environment boundary. For each active agent it builds a compact state from the persona and recent social context, sends typed decision questions to Jev, and converts high-confidence bounded decisions into OASIS `ManualAction`s.

Current direct Jev actions:

```text
DO_NOTHING
LIKE_POST
REPOST          # Twitter
DISLIKE_POST    # Reddit
FOLLOW
```

The generative LLM is retained for actions such as creating original posts/comments/quotes and for decisions below the configured confidence threshold.

The original simulator bodies are preserved as `*_legacy.py`, so the pre-Jev baseline remains reproducible.

## Many possible worlds

The project becomes much more interesting when cheap micro-decisions let us repeat the same world many times.

<div align="center">
<img src="./static/image/jevfish/many-worlds.svg" alt="JevFish many-worlds stochastic simulation concept" width="100%" />
</div>

The intended experiment is:

```text
                     same initial world
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
       rollout 1         rollout 2         rollout 3
          │                 │                 │
         Jev               Jev               Jev
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                  outcome distributions
```

Instead of saying *“the simulator predicts X”*, JevFish should eventually let us ask better questions such as:

- Which outcomes repeatedly emerge across independent rollouts?
- Which outcomes are fragile and disappear with small behavioral changes?
- How much does an intervention at time `T` change downstream simulation frequencies?
- Does the population converge, polarize, fragment, or remain unstable?

## Status

**V0.1 is now on `main`.**

Implemented:

- TypeSafe Jev integration through the official Python SDK;
- `llm`, `hybrid`, and `jev` decision modes;
- typed action and target selection;
- probability sampling for stochastic behavior;
- confidence-based LLM fallback;
- direct OASIS `ManualAction` execution;
- Twitter and Reddit support;
- per-platform JevFish metrics;
- focused runtime tests and GitHub Actions CI;
- preserved legacy simulation entrypoints for exact baseline comparisons.

The next meaningful milestone is not UI polish. It is a controlled **LLM baseline vs JevFish hybrid benchmark** using the same prepared world and seed.

## Decision modes

Set `JEVFISH_DECISION_ENGINE` to one of:

| Mode | Behavior |
|---|---|
| `llm` | Baseline behavior. Every upstream `LLMAction()` stays a generative LLM call. |
| `hybrid` | **Recommended.** Jev executes bounded actions; language and uncertainty fall back to the LLM. |
| `jev` | Jev-only structured stress test. Failed/unsupported Jev decisions become no-ops instead of falling back. |

## Quick start

### Requirements

- Node.js 18+
- Python 3.11–3.12
- `uv`
- TypeSafe API key for Jev
- OpenAI-compatible LLM API key for System-Two actions
- Zep Cloud API key for the graph-memory pipeline

### 1. Configure

```bash
cp .env.example .env
```

Fill in:

```env
# System Two / generative model
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_NAME=...

# System One / Jev
TYPESAFE_API_KEY=...
TYPESAFE_DEFAULT_MODEL=jev-latest
JEVFISH_DECISION_ENGINE=hybrid

# Existing graph-memory pipeline
ZEP_API_KEY=...
```

Optional JevFish controls:

```env
JEVFISH_CONFIDENCE_THRESHOLD=0.58
JEVFISH_MAX_CONTEXT_POSTS=12
JEVFISH_SAMPLE_PROBABILITIES=true
```

`JEVFISH_SAMPLE_PROBABILITIES=true` samples from Jev's returned distributions rather than always taking argmax. This is useful for repeated-world experiments because the same persona does not become a fully deterministic policy.

### 2. Install

```bash
npm run setup:all
```

### 3. Run

```bash
npm run dev
```

Default services:

- frontend: `http://localhost:3000`
- backend: `http://localhost:5001`

## Benchmark the core thesis

Run the **same prepared simulation** twice.

Baseline:

```bash
JEVFISH_DECISION_ENGINE=llm
```

Hybrid:

```bash
JEVFISH_DECISION_ENGINE=hybrid
```

Compare:

- wall-clock runtime;
- total Jev calls;
- LLM fallbacks;
- estimated LLM calls avoided;
- actions per second;
- cost;
- action-type distribution;
- network evolution;
- report divergence;
- stability across repeated stochastic rollouts.

Each platform writes a JevFish metrics file next to the simulation database:

```text
jevfish_twitter_metrics.json
jevfish_reddit_metrics.json
```

The important question is **not only whether JevFish is cheaper**. It is whether System-One micro-agents preserve enough useful population behavior that the saved computation can be reinvested into many more independent trajectories.

## Architecture files

```text
backend/scripts/
├── jevfish_runtime.py                 # Jev integration + OASIS proxy
├── run_parallel_simulation.py         # JevFish wrapper
├── run_parallel_simulation_legacy.py  # preserved baseline implementation
├── run_twitter_simulation.py          # JevFish wrapper
├── run_twitter_simulation_legacy.py   # preserved baseline implementation
├── run_reddit_simulation.py           # JevFish wrapper
└── run_reddit_simulation_legacy.py    # preserved baseline implementation
```

See [`JEVFISH.md`](./JEVFISH.md) for the implementation and experiment notes.

## Roadmap

- **V0.1 — Hybrid action engine** ✅ bounded Jev decisions + System-Two fallback.
- **V0.2 — Jev activity policy** — replace random activation with persona/time/context-conditioned activity decisions.
- **V0.3 — Explicit belief state** — track compact per-agent beliefs, trust, affinities, and exposure-driven updates.
- **V0.4 — Monte Carlo worlds** — run identical initial conditions through many stochastic rollouts.
- **V0.5 — Intervention branches** — fork a world at time `T`, inject different interventions, and compare downstream distributions.
- **V0.6 — Calibration study** — compare simulation frequencies and behavioral distributions against held-out real observations.

## Upstream and acknowledgements

JevFish is derived from [MiroFish](https://github.com/666ghj/MiroFish) and retains substantial upstream infrastructure for graph construction, persona generation, social simulation, interviews, reporting, and Zep-backed memory.

It also builds on:

- [TypeSafe AI / Jev](https://typesafe.ai/) — System-One typed probabilistic decision model;
- [OASIS](https://github.com/camel-ai/oasis) — social interaction simulation environment.

JevFish retains the repository's **AGPL-3.0** license and upstream attribution.
