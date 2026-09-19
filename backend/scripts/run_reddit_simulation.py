"""JevFish entrypoint for the original Reddit MiroFish/OASIS simulator.

The untouched upstream implementation lives in run_reddit_simulation_legacy.py.
This wrapper installs the Jev System-One action layer before running it.
"""

import asyncio

import run_reddit_simulation_legacy as legacy
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
        print("JevFish simulation process exited")
