"""JevFish entrypoint for the original Reddit MiroFish/OASIS simulator.

The untouched upstream implementation lives in run_reddit_simulation_legacy.py.
This wrapper installs the Jev System-One action layer before running it.
"""

import asyncio

import run_reddit_simulation_legacy as legacy
from jevfish_observation import install_oasis_observations
from jevfish_policy_calibration import install_adaptive_thresholds
from jevfish_reproducibility import apply_reproducibility
from jevfish_runtime import install_jevfish
from jevfish_step_alignment import install_step_alignment
from jevfish_system_two import install_system_two_retry


engine = install_jevfish(legacy)
apply_reproducibility(engine)
install_adaptive_thresholds(engine)
install_oasis_observations(engine)
install_step_alignment(engine)
install_system_two_retry(engine)


if __name__ == "__main__":
    if hasattr(legacy, "setup_signal_handlers"):
        legacy.setup_signal_handlers()
    try:
        asyncio.run(legacy.main())
    except KeyboardInterrupt:
        print("\nSimulation interrupted")
    except SystemExit:
        pass
    finally:
        print("JevFish simulation process exited")
