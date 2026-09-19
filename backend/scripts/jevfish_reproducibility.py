"""Best-effort reproducibility controls for JevFish experiments.

The seed controls local stochasticity used by the simulator and recommendation
sampling. Remote model providers can still be nondeterministic, so scientific
benchmarks should use repeated trials rather than treating one seeded run as an
exactly reproducible model outcome.
"""

from __future__ import annotations

import os
import random
import sys
from typing import Any


def _parse_seed(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        # Stable, process-independent fallback for human-readable seed labels.
        value = 0
        for byte in raw.encode("utf-8"):
            value = ((value * 131) + byte) & 0x7FFFFFFF
        return value


def apply_reproducibility(engine: Any | None = None) -> int | None:
    """Seed local RNGs from ``JEVFISH_SEED`` and record the resolved seed."""
    seed = _parse_seed(os.getenv("JEVFISH_SEED"))
    if seed is None:
        if engine is not None:
            engine.stats["seed"] = None
        return None

    random.seed(seed)

    # OASIS pulls in NumPy/Torch in production. Seed them only when already
    # imported so this helper does not make lightweight unit tests expensive.
    numpy = sys.modules.get("numpy")
    if numpy is not None:
        try:
            numpy.random.seed(seed % (2**32))
        except Exception:
            pass

    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            torch.manual_seed(seed)
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
        except Exception:
            pass

    if engine is not None:
        engine.stats["seed"] = seed

    print(f"[JevFish] local simulation seed={seed}")
    return seed
