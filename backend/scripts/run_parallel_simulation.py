"""JevFish entrypoint for the original parallel MiroFish/OASIS simulator.

The untouched upstream implementation lives in run_parallel_simulation_legacy.py.
This wrapper installs the Jev System-One action layer before running it.
"""

import asyncio

import run_parallel_simulation_legacy as legacy
from jevfish_runtime import install_jevfish


install_jevfish(legacy)


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
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("JevFish simulation process exited")
