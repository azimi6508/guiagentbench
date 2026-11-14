"""Checkout-local run viewer; no package installation needed on the host."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.viewer.app import main

raise SystemExit(main(default_root=ROOT / 'runs'))
