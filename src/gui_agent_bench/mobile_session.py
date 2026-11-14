"""Trusted host driver lifetime, attached only to a private application relay."""

import json
import os
import secrets
import signal
import subprocess

from gui_agent_bench.docker import docker, inspect
from gui_agent_bench.io import dump
from gui_agent_bench.mobile_host import native_python, native_environment


def relay_args(platform):
    return ['-i'] if platform == 'mobile' else []


class MobileSession:
    def __init__(self, task, variant, app, folder):
        self.processes, self.streams = [], []
        root = task.parents[2]
        self.root = root
        python = native_python(root)
        if not python.is_file():
            raise RuntimeError('Run scripts/mobile_setup.py prepare first')
        from gui_agent_bench.native_application import declared_application

        dump(
            folder / 'native-application.json',
            declared_application(root, task.relative_to(root / 'tasks').as_posix(), variant),
        )
        secret = secrets.token_hex(32)
        try:
            # The relay reads its capability from stdin. Neither Docker inspect
            # nor command logs contain it. Do not publish the RPC (8000) port.
            relay_log = (folder / 'mobile-relay.log').open('wb')
            self.streams.append(relay_log)
            relay = subprocess.Popen(
                ['docker', 'start', '-ai', app],
                stdin=subprocess.PIPE,
                stdout=relay_log,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != 'nt',
            )
            self.processes.append(relay)
            relay.stdin.write((secret + '\n').encode())
            relay.stdin.flush()
            import time

            deadline = time.monotonic() + 15
            while True:
                details = inspect(app)
                if details['State']['Running']:
                    break
                if relay.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('mobile relay failed to start')
                time.sleep(0.1)
            network = next(iter(details['NetworkSettings']['Networks']))
            dump(folder / 'mobile-app-network.json', json.loads(docker('network', 'inspect', network))[0])
            log = (folder / 'mobile-driver.log').open('wb')
            self.streams.append(log)
            # An explicit environment prevents provider credentials reaching ADB.
            env = native_environment(root)
            env['PYTHONPATH'] = str(root / 'src')
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env['GAB_RENDEZVOUS'] = secret
            process = subprocess.Popen(
                [
                    str(python),
                    '-m',
                    'gui_agent_bench.mobile_driver',
                    '--root',
                    str(root),
                    '--task',
                    task.relative_to(root / 'tasks').as_posix(),
                    '--variant',
                    variant,
                    '--relay-container',
                    app,
                    '--record',
                    str(folder / 'mobile-runtime.json'),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != 'nt',
            )
            self.processes.append(process)
            deadline = time.monotonic() + 90
            while not (folder / 'mobile-runtime.json').is_file():
                if process.poll() is not None:
                    raise RuntimeError('native driver failed startup; see mobile-driver.log')
                if time.monotonic() >= deadline:
                    raise RuntimeError('native driver startup timed out')
                time.sleep(0.1)
        except BaseException:
            self.close()
            raise

    def close(self):
        for process in reversed(self.processes):
            if os.name != 'nt':
                # Each owned process started a separate session. Terminate its
                # descendants too, even if the parent has already exited.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                continue
            if process.poll() is None:
                if os.name == 'nt':
                    # Windows venv python.exe launches a second interpreter.
                    # Stop our owned process tree so its device lock cannot
                    # survive the launcher and race the next environment.
                    subprocess.run(
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for stream in self.streams:
            stream.close()


def start_app(task, variant, name, folder, platform):
    if platform == 'mobile':
        return MobileSession(task, variant, name, folder)
    docker('start', name)
    return None
