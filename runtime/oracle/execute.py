"""Untrusted execution entrypoint. Stdout/exit messages are never verdicts."""

import runpy
import sys

sys.path.insert(0, '/opt')
from oracle_api import Page
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--kind', choices=['oracle', 'test'], default='oracle')
kind = parser.parse_args().kind
function = 'test' if kind == 'test' else 'check'
check = runpy.run_path('/artifact/' + kind + '.py').get(function)
if not callable(check):
    raise ValueError(f'{kind}.py must define {function}(page)')
check(Page())
