"""Polling for real browser state without injecting eval into a CSP document.

Keep the application's normal Content-Security-Policy active during HTTP tests.
Each evaluation goes through the browser automation protocol; no application
script, production hook, or mocked transport is needed.
"""
import time


def wait_for(page, expression, *, arg=None, timeout=8000):
    deadline = time.monotonic() + timeout / 1000
    while True:
        result = page.evaluate(expression, arg)
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"Browser condition did not become true: {expression}")
        page.wait_for_timeout(60)
