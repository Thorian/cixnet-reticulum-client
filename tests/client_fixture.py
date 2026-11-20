"""Run a loopback client with cheap, valid network stamps for protocol tests.

Production keeps upstream stamp costs. Cold production stamps are deliberately
expensive and would turn every isolated test identity into minutes of CPU work.
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import RNS

    RNS.Transport.DESTINATION_VALUE = 8
    RNS.Transport.DESTINATION_COST = 8
    RNS.Transport.PR_VALUE = 8
    RNS.Transport.PR_COST = 8
    runpy.run_path(str(ROOT / "server.py"), run_name="__main__")


if __name__ == "__main__":
    main()
