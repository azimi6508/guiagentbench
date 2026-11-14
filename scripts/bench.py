"""Checkout-local entrypoint; no package installation needed on the host."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gui_agent_bench.entrypoint import main

raise SystemExit(main())
