"""Keep exact gateway stdout audit records separate from stderr diagnostics."""

from pathlib import Path
import json
import subprocess

from gui_agent_bench.docker import client_environment
from gui_agent_bench.failures import Failure
from gui_agent_bench.io import digest, dump, regular_file, strict_json

CONTRACT = 'cursor-provider-streams-v1'


def collect_gateway_logs(name, stdout_path, stderr_path, manifest_path=None, *, contract=CONTRACT):
    result = subprocess.run(['docker', 'logs', name], capture_output=True, timeout=120, env=client_environment())
    stdout_path, stderr_path = Path(stdout_path), Path(stderr_path)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    if manifest_path is not None:
        dump(
            Path(manifest_path),
            dict(
                schema=contract,
                exit_code=result.returncode,
                stdout_bytes=len(result.stdout),
                stderr_bytes=len(result.stderr),
                stdout_sha256=digest(result.stdout),
                stderr_sha256=digest(result.stderr),
            ),
        )
    if result.returncode:
        raise Failure('incomplete_trajectory')


def provider_records(path):
    rows = []
    for line in Path(path).read_bytes().splitlines():
        if not line:
            continue
        value = strict_json(line)
        if not isinstance(value, dict):
            raise ValueError('Provider audit record must be an object')
        json.dumps(value, allow_nan=False, ensure_ascii=False)
        rows.append(value)
    if not rows:
        raise ValueError('Missing provider audit records')
    return rows


def validate_streams(stdout_path, stderr_path, manifest_path, *, contract=CONTRACT):
    root = Path(stdout_path).parent
    stdout = regular_file(Path(stdout_path), root, 64_000_000)
    stderr = regular_file(Path(stderr_path), root, 64_000_000)
    proof = strict_json(regular_file(Path(manifest_path), root, 65_536))
    expected = dict(
        schema=contract,
        exit_code=0,
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        stdout_sha256=digest(stdout),
        stderr_sha256=digest(stderr),
    )
    if proof != expected or stderr:
        raise ValueError('Provider stream evidence differs or contains unexpected stderr')
    return provider_records(stdout_path)
