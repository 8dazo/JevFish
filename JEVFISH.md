# JevFish

JevFish is a System-One simulation fork of MiroFish. It keeps MiroFish/OASIS for world construction, personas, social platforms, interviews, graph memory, and reports, while moving high-frequency bounded social decisions to TypeSafe AI's Jev model.

## Thesis

A social simulation should not spend a generative LLM call on every micro-decision. Most turns are bounded choices: ignore, like, repost, downvote, follow, or escalate to a generative action.

JevFish uses:

- **Jev / System One** for fast structured reactions.
- **The existing LLM / System Two** for original text and ambiguous decisions.
- **OASIS** as the simulation physics and action executor.

The runtime is intentionally hybrid rather than a full rewrite.

## Runtime flow

```text
active OASIS agent
       |
       v
 recent feed + persona
       |
       v
      Jev
       |
       +--> do_nothing ------> ManualAction(DO_NOTHING)
       +--> like ------------> ManualAction(LIKE_POST)
       +--> repost ----------> ManualAction(REPOST)
       +--> dislike ---------> ManualAction(DISLIKE_POST)
       +--> follow ----------> ManualAction(FOLLOW)
       |
       +--> generate / low confidence / error
                    |
                    v
                LLMAction()
```

The existing simulator files are preserved as `*_legacy.py`. The normal entrypoints are thin wrappers that install `jevfish_runtime.py` before running the preserved implementation.

## Modes

Set `JEVFISH_DECISION_ENGINE`:

- `llm`: exact baseline path; every upstream `LLMAction()` stays an `LLMAction()`.
- `hybrid`: Jev handles bounded actions and delegates language/uncertain decisions to the LLM. This is the recommended mode.
- `jev`: structured Jev mode. Jev errors become no-ops rather than generative fallbacks. This is useful for stress tests, not yet the default.

Required for Jev modes:

```bash
TYPESAFE_API_KEY=...
TYPESAFE_DEFAULT_MODEL=jev-latest
```

Useful controls:

```bash
JEVFISH_CONFIDENCE_THRESHOLD=0.58
JEVFISH_MAX_CONTEXT_POSTS=12
JEVFISH_SAMPLE_PROBABILITIES=true
```

Sampling the returned probabilities is deliberate: simulations should preserve stochastic variation instead of turning every persona into an argmax policy.

## Metrics

Each simulated platform writes a `jevfish_<platform>_metrics.json` file beside its SQLite simulation database. Current counters include:

- Jev calls
- direct Jev-backed manual actions
- LLM fallbacks
- untouched manual/interview actions
- Jev errors
- manual action counts by action type

## First benchmark

Run the same prepared simulation and seed/config in two modes:

```bash
JEVFISH_DECISION_ENGINE=llm
# run simulation

JEVFISH_DECISION_ENGINE=hybrid
# run the same simulation again
```

Compare:

1. wall-clock simulation time;
2. number of generative LLM calls avoided;
3. estimated LLM and Jev cost;
4. actions/second;
5. action-type distribution;
6. graph/network evolution;
7. final report divergence;
8. stability across repeated stochastic runs.

The goal is not merely to make MiroFish cheaper. The research question is whether fast calibrated System-One agents let us run many more trajectories while retaining useful population-level behavior.

## Next milestones

1. **V0.1 — hybrid action engine**: current branch. Jev executes bounded social actions and delegates free-form language.
2. **V0.2 — Jev activation policy**: replace random activity scheduling with persona/time/context-conditioned activity probabilities.
3. **V0.3 — explicit belief state**: track compact per-agent beliefs/affinities and let Jev update them after exposure.
4. **V0.4 — Monte Carlo worlds**: fork the same initial world into many stochastic Jev-driven runs and aggregate outcome frequencies.
5. **V0.5 — interventions**: branch a world at time T, inject an event in one branch, and compare downstream distributions.

Simulation frequencies must be reported as simulation outputs, not calibrated real-world probabilities, unless separately validated against real observations.
