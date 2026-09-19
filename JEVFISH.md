# JevFish

JevFish is a hybrid System-One / System-Two social-simulation runtime built on
the MiroFish + OASIS stack. It keeps the existing world construction, personas,
social platforms, graph memory, interviews, and reporting pipeline, while moving
high-frequency behavioral decisions into TypeSafe AI's Jev model.

## Thesis

A social simulation should not spend a full generative-agent turn deciding every
small reaction.

JevFish separates **behavior selection** from **language generation**:

- **Jev / System One** decides which bounded behaviors are plausible and selects
  independent targets.
- **System Two** is called only when an already-selected behavior needs text, or
  when Jev is too uncertain to safely choose a behavior.
- **OASIS** remains the simulation physics and action executor.

The research question is not merely whether this is cheaper. It is whether the
hybrid policy preserves enough useful population behavior that the saved
computation can be reinvested into many more independent rollouts.

## V0.2 runtime flow

```text
active OASIS agent
       |
       v
persona + recent feed
       |
       v
      Jev
  one parallel plan
       |
       +--> refresh? --------+
       +--> like? + target --+
       +--> repost? + target +
       +--> follow? + target +----> OASIS ManualAction[]
       +--> dislike? + target+
       |                     |
       +--> create post? ----+----> System Two writes text
       +--> quote? + target -+              |
       +--> comment?+target -+              v
       |                              targeted ManualAction
       |
       +--> no confident action
                    |
                    +--> no-op, or full LLMAction fallback
                         when hybrid confidence policy requires it
```

OASIS natively accepts a list of `ManualAction` / `LLMAction` objects for one
agent in one timestep, so JevFish action bundles execute within the same OASIS
clock tick rather than advancing the simulation once per micro-action.

### Why the text path is constrained

When Jev selects `create_post`, `quote`, or a Reddit `comment`, JevFish does not
normally hand the entire turn back to an unrestricted generative agent.

Instead:

1. Jev decides that the language action should happen.
2. Jev selects the target when the action needs one.
3. System Two generates only the text.
4. JevFish executes a targeted OASIS `CREATE_POST`, `QUOTE_POST`, or
   `CREATE_COMMENT` manual action.

If that text-generation request fails, hybrid mode can still fall back to the
original `LLMAction()` path.

## Decision modes

Set `JEVFISH_DECISION_ENGINE`:

- `llm` — exact OASIS baseline. Every intercepted `LLMAction()` remains an
  `LLMAction()`.
- `hybrid` — recommended. Jev plans behavior; System Two materializes selected
  language actions; uncertainty can escalate to the full OASIS LLM agent.
- `jev` — structured Jev stress test. No generative text is required and
  unsupported/generative decisions can become no-ops.

## Policy modes

Set `JEVFISH_POLICY_MODE`:

- `multi` — V0.2 default. One Jev request produces a sparse multi-action bundle.
- `single` — preserved V0.1 router. One Jev request chooses one mutually
  exclusive action. Useful for compatibility and ablations.

Useful controls:

```bash
JEVFISH_CONFIDENCE_THRESHOLD=0.58
JEVFISH_MAX_CONTEXT_POSTS=12
JEVFISH_MAX_ACTIONS_PER_AGENT=3
JEVFISH_MAX_SYSTEM_TWO_ACTIONS=1
JEVFISH_SAMPLE_PROBABILITIES=true
```

For controlled A/B benchmarks, set probability sampling to `false`. For
many-world stochastic experiments, sampling can be enabled again.

## Metrics

Each platform writes `jevfish_<platform>_metrics.json` beside its SQLite
simulation database.

V0.2 tracks:

- `jev_calls`
- `jev_plans`
- `jev_manual_actions`
- `multi_action_agents`
- `llm_fallbacks`
- `llm_escalations`
- `system_two_calls`
- `system_two_errors`
- `uncertain_gates`
- selected behavior counts
- executed manual action counts
- System-Two generation counts by action type

These counters distinguish three materially different things:

1. a Jev behavioral plan;
2. a constrained System-Two text request;
3. a full OASIS `LLMAction()` fallback.

That distinction matters when evaluating cost and fidelity.

## Controlled A/B benchmark

The repository includes:

```text
benchmarks/jevfish_ab.py
```

It builds one synthetic society and executes two production OASIS worlds with
the same personas, initial posts, activation schedule, and round count:

```text
A: hybrid + multi-action Jev policy
B: LLM-only OASIS baseline
```

Example:

```bash
export TYPESAFE_API_KEY=...
export LLM_API_KEY=...
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_MODEL_NAME=meta/muse-spark-1.3-contributor

python benchmarks/jevfish_ab.py \
  --agents 10 \
  --rounds 3 \
  --threshold 0.58 \
  --max-actions 3
```

The report includes:

- total and simulation-loop runtime;
- Jev calls and plans;
- constrained System-Two requests;
- full LLM fallback turns;
- expensive model turns avoided;
- OASIS trace action counts;
- generated-post / follow / like counts;
- action-distribution similarity.

`action_distribution_similarity` is `1 - total variation distance` over the
observed action-frequency distributions after removing sign-up events and the
two fixed seed posts. It measures agreement between these two simulation
policies. It is **not** a measure of real-world predictive accuracy.

## Testing

Fast CI covers the runtime and benchmark arithmetic without provider calls:

```bash
python -m pytest -q \
  tests/test_jevfish_runtime.py \
  tests/test_jevfish_benchmark.py
```

Provider-backed workflows are intentionally manual because they spend API
credits:

- `JevFish live smoke`
- `JevFish live OASIS integration`
- `JevFish live OASIS LLM baseline`
- `JevFish A/B benchmark`

## Scientific caution

More rollouts do not magically produce real-world probabilities. A hundred
JevFish worlds give a more precise estimate of the distribution induced by the
configured simulator and policy. Real forecasting claims would require
calibration and validation against held-out observations.

The near-term evaluation target is therefore:

> How much expensive generative-agent computation can the hybrid policy remove
> while keeping aggregate simulated behavior close to an LLM-only baseline?

## Roadmap

1. **V0.1 — single-action hybrid router** ✅
2. **V0.2 — multi-action behavioral policy + targeted language + A/B harness** ✅
3. **V0.3 — activity policy** — replace random activation with
   persona/time/context-conditioned activity.
4. **V0.4 — explicit belief state** — maintain compact beliefs, trust,
   affinities, and exposure-driven updates.
5. **V0.5 — Monte Carlo worlds** — repeat identical initial conditions under
   independent stochastic seeds.
6. **V0.6 — intervention branches** — fork a world at time `T`, inject
   different events, and compare downstream simulation distributions.
7. **V0.7 — calibration study** — compare model-level behavior against held-out
   real observations before making any real-world predictive claims.
