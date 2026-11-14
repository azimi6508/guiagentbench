#!/usr/bin/env python3
"""Run the AURA app with an isolated, reproducible benchmark fixture.

This controller is outside the evaluated workspace. Only the selected app
implementation and ordinary initial user state are served to the browser.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
import importlib.util
import io
import json
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
import threading
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
APP = HERE / "app"
# Keep the supplied source tree immutable during local imports and previews.
sys.dont_write_bytecode = True
module_spec = importlib.util.spec_from_file_location("aura_application_server", APP / "server.py")
aura = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(aura)


def selected_files(spec, faulty=False):
    """Apply exact, bounded replacements to an in-memory copy; never edit source."""
    output = {}
    patches = spec.get("mutation", [])
    if isinstance(patches, dict):
        patches = [patches]
    for patch in patches:
        relative = patch["file"]
        path = (APP / relative).resolve()
        if not path.is_relative_to(APP) or not relative.startswith("src/") or path.suffix not in {".js", ".css"}:
            raise ValueError("Mutation target is not an application source file")
        original = output.get(relative, path.read_text(encoding="utf-8"))
        count = patch.get("count", 1)
        if not patch["old"] or original.count(patch["old"]) != count:
            raise ValueError(f"Mutation anchor mismatch: {spec['id']} / {relative}")
        if patch["old"] == patch["new"]:
            raise ValueError("Mutation must change a behavior")
        output[relative] = original.replace(patch["old"], patch["new"], count)
    return output if faulty else {}


def seed_for(spec):
    defaults = json.loads((HERE / "defaults.json").read_text(encoding="utf-8"))
    defaults.update(showClock=False, reducedMotion=True, autoplay=False, navSounds=False)
    supplied = spec.get("seed", {})
    defaults.update(supplied.get("settings", {}))
    profiles = {name: {"watchlist": [], "history": {}} for name in ("alex", "guest", "kids")}
    for name, values in supplied.get("profiles", {}).items():
        if name not in profiles:
            raise ValueError("Invalid fixture profile")
        profiles[name].update(values)
    return {
        "version": 3,
        "settings": defaults,
        "profile": supplied.get("profile", "alex"),
        "profiles": profiles,
        "links": supplied.get("links", []),
    }


class AppServer(aura.Server):
    def __init__(self, address, spec, faulty=False, *, data_dir=None):
        self.fixture = spec
        self.files = selected_files(spec, faulty)
        self.seed = seed_for(spec)
        self.guard = threading.RLock()
        self.session = None
        self._temporary = tempfile.TemporaryDirectory(prefix="aura-bench-") if data_dir is None else None
        self.data_path = Path(self._temporary.name if self._temporary else data_dir)
        self.data_path.mkdir(parents=True, exist_ok=True)
        super().__init__(address, partial(AppHandler, directory=str(APP)), aura.Library(self.data_path))
        self.hosts.add(f"app:{self.server_port}")

    def reset(self, session):
        # The request-wide lock excludes old requests while the backend is reset.
        self.session = session
        self.token = secrets.token_urlsafe(32)
        for name in ("files", "thumbs"):
            shutil.rmtree(self.data_path / name, ignore_errors=True)
        for path in self.data_path.glob("library.sqlite3*"):
            path.unlink()
        self.library = aura.Library(self.data_path)

    def server_close(self):
        super().server_close()
        if self._temporary:
            self._temporary.cleanup()


class AppHandler(aura.Handler):
    def valid_session(self):
        # Manual local preview has no admitted session until its first reset.
        if self.server.session is None:
            return True
        if not secrets.compare_digest(self.headers.get("X-GAB-Session", ""), self.server.session):
            self.error(409, "This application session has ended.")
            return False
        return True

    def send_bytes(self, data, mime):
        self.range_bounds = None
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return io.BytesIO(data)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if not self.valid_host():
            self.send_error(403, "Unknown host")
            return None
        if path in ("/", "/index.html"):
            document = (APP / "index.html").read_text(encoding="utf-8")
            document = document.replace(
                '<script type="module" src="src/app.js"></script>',
                '<script src="src/initial-state.js"></script>\n  <script type="module" src="src/app.js"></script>',
            )
            return self.send_bytes(document.encode(), "text/html; charset=utf-8")
        if path == "/src/initial-state.js":
            # Ordinary fixture data is identical for both members of a pair.
            raw = json.dumps(self.server.seed, ensure_ascii=True).replace("</", "<\\/")
            script = (
                "(()=>{if(localStorage.getItem('aura-tv.v3')===null){const state=" + raw + ";"
                "for(const item of state.links){for(const key of ['url','poster'])"
                "if(typeof item[key]==='string')item[key]=item[key].replaceAll('__ORIGIN__',location.origin);}"
                "localStorage.setItem('aura-tv.v3',JSON.stringify(state));}})();\n"
            )
            return self.send_bytes(script.encode(), "text/javascript; charset=utf-8")
        relative = path.lstrip("/")
        if relative in self.server.files:
            return self.send_bytes(self.server.files[relative].encode(), self.guess_type(relative))
        return super().send_head()

    def do_GET(self):
        with self.server.guard:
            if self.valid_session():
                super().do_GET()

    def do_HEAD(self):
        with self.server.guard:
            if self.valid_session():
                super().do_HEAD()

    def do_POST(self):
        with self.server.guard:
            if urlsplit(self.path).path == "/reset":
                session = self.headers.get("X-GAB-Session", "")
                if not self.valid_host() or self.headers.get("Origin") or not re.fullmatch(r"[a-f0-9]{32}", session):
                    self.error(403, "Invalid reset request.")
                    return
                self.server.reset(session)
                self.send_response(204)
                self.send_header("X-GAB-Session", session)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif self.valid_session():
                super().do_POST()

    def do_PUT(self):
        with self.server.guard:
            if self.valid_session():
                super().do_PUT()

    def do_DELETE(self):
        with self.server.guard:
            if self.valid_session():
                super().do_DELETE()

    def log_message(self, fmt, *args):
        # Leave labels, private filenames and fixture data out of app logs.
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)


@contextmanager
def running(spec, faulty=False):
    server = AppServer(("127.0.0.1", 0), spec, faulty)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("/settings.json"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    config = json.loads(args.settings.read_text(encoding="utf-8"))
    if set(config) != {"spec", "fault"} or type(config["fault"]) is not bool:
        parser.error("Invalid private environment configuration")
    spec = config["spec"]
    if not isinstance(spec, dict) or set(spec) - {"id", "seed", "mutation"} or not isinstance(spec.get("id"), str):
        raise ValueError("Invalid task-owned AURA fixture")
    with AppServer((args.host, args.port), spec, config["fault"]) as server:
        print(f"AURA TV ready on port {server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
