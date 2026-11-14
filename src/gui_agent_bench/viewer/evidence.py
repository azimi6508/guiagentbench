"""Versioned, rebuildable display index. Original files remain authoritative.

No harness imports, execution, task directory access, or evidence writes. Source
order is retained: recovery timestamps are never treated as original event time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from gui_agent_bench.failures import model_zero

VERSION = 'viewer-v1'
IMAGE = re.compile(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)')
SAFE_ID = re.compile(r'^[A-Za-z0-9_-]+$')
TEXT_SUFFIXES = {'.json', '.ndjson', '.log', '.txt', '.py', '.md'}


def linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def safe_file(root: Path, relative: str) -> Path:
    # Reject Windows alternate streams, absolute paths, backslashes and aliases
    # even when the viewer is running on POSIX.
    parts = relative.split('/')
    if not relative or any(p in {'', '.', '..'} for p in parts) or any(c in relative for c in '\\:\x00'):
        raise ValueError('Invalid evidence path')
    current = root
    for part in parts:
        current = current / part
        if linked(current):
            raise ValueError('Linked evidence is not served')
    if not current.resolve().is_relative_to(root.resolve()) or not current.is_file():
        raise ValueError('Evidence is not a regular file')
    return current


def allowed(relative: str) -> bool:
    """Positive artifact layout allowlist; no capture/gold/config/container roots."""
    parts = relative.split('/')
    if any(p in {'gold', 'private', 'capture', 'config'} or p.endswith('-container.json') for p in parts):
        return False
    if relative in {'plan.json', 'summary.json', 'audit.json', 'submission.json', 'reference.json'}:
        return True
    # Strip only established structural prefixes; do not trust paths from JSON.
    if len(parts) >= 3 and parts[0] == 'trials' and SAFE_ID.fullmatch(parts[1]):
        return allowed('/'.join(parts[2:]))
    if parts[0] == 'verification':
        return allowed('/'.join(parts[1:]))
    if len(parts) >= 3 and parts[0] == 'executions' and SAFE_ID.fullmatch(parts[1]):
        rest = parts[2:]
        if '/'.join(rest) in {
            'result.json',
            'browser.log',
            'stdout.log',
            'stderr.log',
            'isolation.json',
            'termination.json',
        }:
            return True
        return (
            len(rest) == 3
            and rest[0] == 'image-assertions'
            and rest[1].isdigit()
            and rest[2] in {'result.json', 'capture.png', 'expected.png', 'actual.png', 'diff.png'}
        )
    if len(parts) == 4 and parts[:3] == ['logs', 'bridge', 'images']:
        return bool(re.fullmatch(r'[a-f0-9]{64}\.png', parts[3]))
    if relative in {
        'agent-plan.json',
        'resolved-plan.json',
        'runtime-manifest.json',
        'preflight.json',
        'logs/agent/cursor.ndjson',
        'logs/agent/mcp.ndjson',
        'logs/agent/guard.ndjson',
        'logs/agent/cursor-stderr.log',
        'logs/cursor-provider.ndjson',
        'logs/agent/claude.ndjson',
        'logs/agent/claude-stderr.log',
        'logs/claude-provider.ndjson',
        'logs/agent/codex-rpc.ndjson',
        'logs/agent/normalized.ndjson',
        'logs/agent/codex-stderr.log',
        'logs/agent/startup.json',
        'logs/bridge/bridge.ndjson',
        'logs/egress.ndjson',
    }:
        return True
    if relative in {
        'logs/agent/trajectory.ndjson',
        'logs/agent/summary.json',
        'logs/agent/stderr.log',
        'logs/browser.ndjson',
        'logs/provider.ndjson',
        'logs/verifier/metrics.json',
        'logs/verifier/reward.json',
        'logs/verifier/reward.txt',
        'workspace/instruction.md',
        'workspace/steps.json',
        'workspace/test_source.py',
        'workspace/manifest.json',
        'workspace/evidence/manifest.json',
        'workspace-manifest.json',
        'isolation.json',
        'broker-isolation.json',
        'cleanup.json',
        'effective-config.json',
        'mobile-driver.log',
        'mobile-relay.log',
    }:
        return True
    if len(parts) == 3 and parts[:2] == ['workspace', 'screenshots']:
        return bool(re.fullmatch(r'[A-Za-z0-9_-]+\.png', parts[2]))
    if len(parts) == 4 and parts[:3] == ['workspace', 'evidence', 'screenshots']:
        return bool(re.fullmatch(r'[A-Za-z0-9_-]+\.png', parts[3]))
    if len(parts) == 2 and parts[0] == 'output':
        return parts[1] in {'test.py', 'oracle.py', 'judgment.json'}
    if parts[0] == 'sealed':
        if len(parts) == 2 and parts[1] in {'test.py', 'oracle.py', 'judgment.json'}:
            return True
        if len(parts) == 3 and parts[1] == 'references':
            return bool(re.fullmatch(r'[A-Za-z0-9_-]+\.(png|json)', parts[2]))
    return False


def strict_constant(name):
    raise ValueError('non-finite number in JSON record: ' + name)


def json_file(root: Path, relative: str) -> tuple[dict, str | None]:
    try:
        value = json.loads(safe_file(root, relative).read_text(encoding='utf-8'), parse_constant=strict_constant)
        if not isinstance(value, dict):
            return {}, 'Expected an object'
        return value, None
    except FileNotFoundError:
        return {}, 'Not recorded yet or missing'
    except (ValueError, OSError, UnicodeError):
        return {}, 'Unreadable, incomplete or invalid record'


def trial_issues(root: Path, plan: dict) -> list[dict]:
    """Recorded failure-v1 diagnostics of every planned trial."""
    issues = []
    for trial in plan.get('trials') or []:
        identifier = trial.get('id') if isinstance(trial, dict) else None
        if isinstance(identifier, str) and SAFE_ID.fullmatch(identifier):
            metrics, _ = json_file(root, f'trials/{identifier}/logs/verifier/metrics.json')
            recorded = metrics.get('diagnostics')
            recorded = recorded.get('issues') if isinstance(recorded, dict) else None
            issues.extend(i for i in recorded or [] if isinstance(i, dict))
    return issues


def walk(root: Path):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not linked(Path(directory) / d))
        for name in sorted(files):
            path = Path(directory) / name
            if not linked(path):
                yield path


def image_parts(value):
    """Only embedded raster data, never fetch artifact-supplied URLs."""
    if isinstance(value, str):
        for match in IMAGE.finditer(value):
            try:
                data = base64.b64decode(match[2], validate=False)
                mime = 'image/' + match[1]
                valid = (
                    (mime == 'image/png' and data.startswith(b'\x89PNG\r\n\x1a\n'))
                    or (mime == 'image/jpeg' and data.startswith(b'\xff\xd8\xff'))
                    or (mime == 'image/webp' and data[:4] == b'RIFF' and data[8:12] == b'WEBP')
                )
                if valid:
                    yield hashlib.sha256(data).hexdigest(), mime, data
            except ValueError:
                continue
    elif isinstance(value, dict):
        if value.get('type') == 'image' and value.get('mimeType') == 'image/png' and isinstance(value.get('data'), str):
            try:
                data = base64.b64decode(value['data'], validate=True)
                if data.startswith(b'\x89PNG\r\n\x1a\n'):
                    yield hashlib.sha256(data).hexdigest(), 'image/png', data
            except ValueError:
                pass
        for child in value.values():
            yield from image_parts(child)
    elif isinstance(value, list):
        for child in value:
            yield from image_parts(child)


def display_value(value):
    if isinstance(value, str):
        return IMAGE.sub('[embedded image: available in observations and original source]', value)
    if isinstance(value, dict):
        if value.get('type') == 'image' and 'data' in value:
            return {k: v for k, v in value.items() if k != 'data'} | {
                'data': '[original image available in observations]'
            }
        return {k: display_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [display_value(v) for v in value]
    return value


def obj(value):
    return value if isinstance(value, dict) else {}


class EvidenceIndex:
    def __init__(self, root: Path):
        # Resolve the chosen directory once; links are refused only inside the evidence below it.
        self.root = root.absolute().resolve()
        if not self.root.is_dir():
            raise ValueError('Run directory does not exist')
        self.lock = threading.RLock()
        self.runs = {}
        self.collections = []
        self.last_scan = 0
        self.streams = {}

    def refresh(self, force=False):
        with self.lock:
            if not force and time.monotonic() - self.last_scan < 3:
                return
            found = {}
            collections = []
            for directory, dirs, files in os.walk(self.root, followlinks=False):
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if not linked(Path(directory) / d)
                    and d
                    not in {'workspace', 'sealed', 'capture', 'gold', 'logs', 'executions', 'verification', 'config'}
                )
                path = Path(directory)
                if 'run.json' in files:
                    collections.append(path)
                if 'plan.json' not in files:
                    continue
                plan, error = json_file(path, 'plan.json')
                if not error and not plan.get('arm') and ('planned_task_arm_pairs' in plan):
                    collections.append(path)
                if error or not plan.get('arm') or not (plan.get('task') or 'executions' in plan):
                    continue
                key = path.relative_to(self.root).as_posix()
                run_id = hashlib.sha256(key.encode()).hexdigest()[:20]
                found[run_id] = (path, key)
                dirs[:] = []  # verification plans belong to their parent run
            self.runs = found
            self.collections = collections
            self.last_scan = time.monotonic()

    def directory(self, run_id):
        if run_id not in self.runs:
            self.refresh()
        if run_id not in self.runs:
            raise FileNotFoundError('Run not found')
        path = self.runs[run_id][0]
        # Recheck ancestors on every request, including after index creation.
        if any(linked(p) for p in [path, *path.parents]):
            raise ValueError('Linked directory rejected')
        return path

    def sha256(self, run_id, relative, warnings):
        """Hash one evidence file; an unreadable file becomes a warning, not a failed page."""
        try:
            return hashlib.sha256(self.artifact(run_id, relative).read_bytes()).hexdigest()
        except OSError:
            warnings.append({'file': relative, 'message': 'Unreadable file; its recorded hash could not be checked'})
            return None

    def artifact(self, run_id, relative):
        if not allowed(relative):
            raise ValueError('Artifact is not in the evidence allowlist')
        return safe_file(self.directory(run_id), relative)

    def listing(self):
        self.refresh()
        rows = []
        for run_id in list(self.runs):
            try:
                root = self.directory(run_id)
                plan, error = json_file(root, 'plan.json')
                summary, summary_error = json_file(root, 'summary.json')
                if 'executions' in plan:
                    summary, summary_error = json_file(root, 'logs/verifier/metrics.json')
                modified = max(
                    (root / 'plan.json').stat().st_mtime,
                    (root / 'summary.json').stat().st_mtime if (root / 'summary.json').exists() else 0,
                )
                state = summary.get('status', 'incomplete')
                score = summary.get('paired_score', summary.get('reward'))
                paired = not (str(plan.get('arm', '')).startswith('judge') and summary.get('planned_pairs') == 0)
                task = plan.get('task', 'External submission')
                rows.append(
                    {
                        'id': run_id,
                        'name': root.name,
                        'path': self.runs[run_id][1],
                        'model_zero': state == 'complete'
                        and bool(summary.get('invalid_or_missing'))
                        and model_zero(
                            trial_issues(root, plan),
                            control=bool(plan.get('fixture') or plan.get('reference') or plan.get('agent_bypassed')),
                        ),
                        'task': task,
                        'platform': task.split('/')[0] if '/' in task else 'unknown',
                        'arm': plan.get('arm'),
                        'model': plan.get('model', 'External submission'),
                        'runner': plan.get('runner', 'opencode'),
                        'agent_spec': plan.get('agent_spec'),
                        'configuration_sha256': plan.get('configuration_sha256'),
                        'parent_resolved_plan_sha256': plan.get('parent_resolved_plan_sha256'),
                        'fixture': plan.get('fixture'),
                        'research_core': plan.get('research_core'),
                        'reference': plan.get('reference'),
                        'agent_bypassed': plan.get('agent_bypassed'),
                        'task_status': plan.get('task_status', 'unknown'),
                        'contract': (
                            'codex-bounded-v1:' + plan.get('resolved_plan_sha256', 'unattested')
                            if plan.get('runner') == 'codex'
                            else plan.get('action_contract', plan.get('abi', 'historical / unknown'))
                        ),
                        'planned': plan.get('planned_trials', plan.get('planned_executions')),
                        'completed': summary.get('completed_trials', summary.get('completed_executions')),
                        'status': state,
                        'score': score,
                        'paired': paired,
                        'modified': modified,
                        'invalid_or_missing': summary.get('invalid_or_missing'),
                        'warning': error or summary_error,
                        'outcome': (
                            'unresolved'
                            if state in {'running', 'incomplete'}
                            else (
                                'unpaired'
                                if not paired
                                else 'success' if score == 1 else 'zero credit' if score == 0 else 'unresolved'
                            )
                        ),
                    }
                )
            except (OSError, ValueError):
                continue
        return {
            'version': VERSION,
            'runs': sorted(rows, key=lambda r: r['modified'], reverse=True),
            'scanned_at': time.time(),
        }

    def hierarchy(self):
        from .hierarchy import project

        return project(self, self.listing()['runs'])

    def detail(self, run_id):
        root = self.directory(run_id)
        plan, plan_error = json_file(root, 'plan.json')
        summary, summary_error = json_file(root, 'summary.json')
        if 'executions' in plan:
            summary, summary_error = json_file(root, 'logs/verifier/metrics.json')
        artifacts, warnings = [], []
        if plan_error:
            warnings.append({'file': 'plan.json', 'message': plan_error})
        if summary_error and 'executions' not in plan:
            warnings.append({'file': 'summary.json', 'message': summary_error})
        for path in walk(root):
            relative = path.relative_to(root).as_posix()
            if allowed(relative):
                info = path.stat()
                artifacts.append(
                    {'path': relative, 'size': info.st_size, 'modified': info.st_mtime, 'image': path.suffix == '.png'}
                )
        paths = {a['path'] for a in artifacts}

        def read(relative):
            data, error = json_file(root, relative)
            if error:
                warnings.append({'file': relative, 'message': error})
            return data

        trials = []
        planned = plan.get('trials') or []
        if 'executions' in plan:
            planned = [{'id': 'external', 'variant': 'authoring'}]
        for cell in planned:
            trial_id = cell.get('id', '')
            if not SAFE_ID.fullmatch(trial_id):
                warnings.append({'file': 'plan.json', 'message': 'Invalid planned trial identifier'})
                continue
            prefix = '' if trial_id == 'external' else f'trials/{trial_id}/'
            metrics_path = prefix + 'logs/verifier/metrics.json'
            metrics = read(metrics_path)
            verification = prefix + 'verification/' if trial_id != 'external' else ''
            pair_plan = (
                plan
                if trial_id == 'external'
                else (read(verification + 'plan.json') if verification + 'plan.json' in paths else {})
            )
            executions = []
            for execution in pair_plan.get('executions', []):
                eid = execution.get('id', '')
                if not SAFE_ID.fullmatch(eid):
                    continue
                ep = verification + f'executions/{eid}/'
                result = read(ep + 'result.json')
                images = []
                for artifact in artifacts:
                    ap = artifact['path']
                    if ap.startswith(ep + 'image-assertions/') and ap.endswith('/result.json'):
                        images.append({'path': ap, 'directory': ap.rsplit('/', 1)[0], 'result': read(ap)})
                executions.append(
                    {
                        'id': eid,
                        'variant': execution.get('variant', 'unknown'),
                        'path': ep + 'result.json',
                        'result': result,
                        'images': images,
                    }
                )
            streams = [
                p
                for p in (
                    prefix + 'logs/agent/codex-rpc.ndjson',
                    prefix + 'logs/agent/normalized.ndjson',
                    prefix + 'logs/bridge/bridge.ndjson',
                    prefix + 'logs/agent/trajectory.ndjson',
                    prefix + 'logs/browser.ndjson',
                    prefix + 'logs/provider.ndjson',
                    *(verification + f"executions/{e['id']}/browser.log" for e in executions),
                )
                if p in paths
            ]
            resources = {
                'authoring_seconds': None,
                'input_tokens': None,
                'output_tokens': None,
                'reasoning_tokens': None,
                'recorded_steps': 0,
            }
            agent_summary = prefix + 'logs/agent/summary.json'
            if agent_summary in paths:
                resources['authoring_seconds'] = read(agent_summary).get('elapsed_seconds')
            trajectory = prefix + 'logs/agent/trajectory.ndjson'
            observations, finishes, reads, read_parts = {}, {}, {}, {}
            if trajectory in paths:
                for line, _, event, _ in self.records(run_id, trajectory):
                    part = obj(event.get('part'))
                    if event.get('type') == 'step_finish':
                        finishes[(event.get('sessionID'), part.get('messageID'), part.get('id') or line)] = part
                    for sha, _, _ in image_parts(event):
                        observations.setdefault(sha, {'file': trajectory, 'line': line})
                    state = obj(part.get('state'))
                    args = obj(state.get('input'))
                    if part.get('tool') == 'read':
                        identity = (event.get('sessionID'), part.get('messageID'), part.get('id') or line)
                        read_parts[identity] = (args.get('filePath'), state.get('status'), line)
                for filename, status, line in read_parts.values():
                    if status == 'completed' and isinstance(filename, str) and filename.startswith('/workspace/'):
                        reads.setdefault(filename[len('/workspace/') :], []).append({'file': trajectory, 'line': line})
            workspace_manifest_path = prefix + 'workspace-manifest.json'
            workspace_manifest = read(workspace_manifest_path) if workspace_manifest_path in paths else {}
            offered = obj(workspace_manifest.get('files'))
            input_paths = sorted(
                set(offered) | {p[len(prefix + 'workspace/') :] for p in paths if p.startswith(prefix + 'workspace/')}
            )
            inputs = []
            for name in input_paths:
                ap = prefix + 'workspace/' + name
                # Manifests are data, not authority to read arbitrary paths.
                if not allowed(ap):
                    continue
                present = ap in paths
                actual = self.sha256(run_id, ap, warnings) if present else None
                inputs.append(
                    {
                        'name': name,
                        'path': ap,
                        'present': present,
                        'recorded_sha256': offered.get(name),
                        'actual_sha256': actual,
                        'hash_matches': actual == offered[name] if actual and name in offered else None,
                        'image': name.endswith('.png'),
                        'reads': reads.get(name, []),
                        'observation': observations.get(actual) if actual else None,
                    }
                )
            if trajectory in paths:
                resources['recorded_steps'] = len(finishes)
                for field, key in [
                    ('input_tokens', 'input'),
                    ('output_tokens', 'output'),
                    ('reasoning_tokens', 'reasoning'),
                ]:
                    values = [obj(part.get('tokens')).get(key) for part in finishes.values()]
                    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                        resources[field] = sum(values)
            if plan.get('runner') in {'codex', 'cursor', 'claude'} and agent_summary in paths:
                codex = read(agent_summary)
                usage = obj(codex.get('usage'))
                resources.update(
                    recorded_steps=None,
                    runner=plan['runner'],
                    observed_tool_items=codex.get('observed_tool_items'),
                    input_tokens=usage.get('inputTokens'),
                    output_tokens=usage.get('outputTokens'),
                    reasoning_tokens=usage.get('reasoningOutputTokens'),
                    budget_profile=plan['runner'] + '-bounded-v1',
                )
            references = []
            manifest_path = prefix + 'sealed/references/manifest.json'
            if manifest_path in paths:
                manifest = read(manifest_path)
                for name, reference in obj(manifest.get('references')).items():
                    reference = obj(reference)
                    rp = prefix + 'sealed/references/' + str(reference.get('file', ''))
                    actual_hash = None
                    if rp in paths:
                        actual_hash = self.sha256(run_id, rp, warnings)
                    references.append(
                        {
                            'name': name,
                            'file': rp,
                            'recorded_sha256': reference.get('sha256'),
                            'actual_sha256': actual_hash,
                            'hash_matches': actual_hash == reference.get('sha256') if actual_hash else None,
                            'observation': observations.get(actual_hash),
                        }
                    )
            sealed = next(
                (
                    prefix + 'sealed/' + name
                    for name in ('test.py', 'oracle.py', 'judgment.json')
                    if prefix + 'sealed/' + name in paths
                ),
                None,
            )
            submission = read(prefix + 'submission.json') if prefix + 'submission.json' in paths else {}
            actual_sha = self.sha256(run_id, sealed, warnings) if sealed else None
            trials.append(
                {
                    'id': trial_id,
                    'variant': cell.get('variant'),
                    'prefix': prefix,
                    'metrics_path': metrics_path,
                    'metrics': metrics,
                    'executions': executions,
                    'pair_plan': pair_plan,
                    'streams': streams,
                    'submission': submission,
                    'sealed_file': sealed,
                    'sealed_actual_sha256': actual_sha,
                    'sealed_hash_matches': actual_sha == submission.get('sha256') if actual_sha else None,
                    'resources': resources,
                    'references': references,
                    'inputs': inputs,
                    'workspace_manifest': workspace_manifest_path if workspace_manifest_path in paths else None,
                    'draft_files': [p for p in sorted(paths) if p.startswith(prefix + 'output/')],
                    'missing': not any(p.startswith(prefix) for p in paths),
                }
            )
        # Only measured provider usage is summarized. Missing costs never become zero.
        costs, usage_records, unknown_costs = [], 0, 0
        for relative in sorted(p for p in paths if p.endswith('logs/provider.ndjson')):
            for _, _, event, _ in self.records(run_id, relative):
                if isinstance(event.get('usage'), dict):
                    usage_records += 1
                    cost = event['usage'].get('cost')
                    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                        costs.append(cost)
                    else:
                        unknown_costs += 1
        if plan.get('runner') in {'codex', 'cursor', 'claude'}:
            unknown_costs += len(trials)
        audit = read('audit.json') if 'audit.json' in paths else None
        return {
            'version': VERSION,
            'id': run_id,
            'name': root.name,
            'plan': plan,
            'summary': summary,
            'trials': trials,
            'artifacts': artifacts,
            'warnings': warnings,
            'audit': audit,
            'cost': {
                'known_usd': sum(costs) if costs else None,
                'records': usage_records,
                'unknown_records': unknown_costs,
                'coverage': 'recorded usage only; request completeness unknown',
            },
            'last_evidence': max((a['modified'] for a in artifacts), default=None),
        }

    def records(self, run_id, relative):
        path = self.artifact(run_id, relative)
        if path.suffix not in {'.ndjson', '.log'}:
            raise ValueError('Not an event stream')
        with path.open('rb') as source:
            line_number = 0
            while True:
                offset = source.tell()
                line = source.readline()
                if not line:
                    break
                line_number += 1
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                    error = None
                except (ValueError, UnicodeError):
                    event = {'text': line.decode('utf-8', errors='replace')}
                    error = 'Incomplete final record' if not line.endswith(b'\n') else 'Non-JSON record'
                if relative.endswith('logs/agent/codex-rpc.ndjson'):
                    from .codex import envelope

                    event = envelope(event)
                yield line_number, offset, event, error

    def event_index(self, run_id, relative):
        path = self.artifact(run_id, relative)
        info = path.stat()
        signature = (info.st_mtime_ns, info.st_size)
        key = (run_id, relative)
        with self.lock:
            cached = self.streams.get(key)
            if cached and cached[0] == signature:
                return cached[1]
            events, identities = [], {}
            for line, offset, event, error in self.records(run_id, relative):
                part = obj(event.get('part'))
                # Stable part identity represents revisions, not additional calls.
                identity = (event.get('sessionID'), part.get('messageID'), part.get('id')) if part.get('id') else None
                if relative.endswith('logs/agent/codex-rpc.ndjson'):
                    from .codex import identity as codex_identity

                    identity = codex_identity(event)
                revision = {'line': line, 'offset': offset}
                if identity is not None and identity in identities:
                    item = events[identities[identity]]
                    item['revisions'].append(revision)
                    item.update(line=line, offset=offset, error=error)
                else:
                    if identity is not None:
                        identities[identity] = len(events)
                    events.append({'line': line, 'offset': offset, 'error': error, 'revisions': [revision]})
            self.streams[key] = (signature, events)
            # Disposable metadata cache, bounded by number of streams.
            if len(self.streams) > 128:
                self.streams.pop(next(iter(self.streams)))
            return events

    def events(self, run_id, relative, offset=0, limit=60):
        entries = self.event_index(run_id, relative)
        path = self.artifact(run_id, relative)
        values = []
        with path.open('rb') as source:
            for position, entry in enumerate(entries[offset : offset + limit], offset):
                source.seek(entry['offset'])
                raw = source.readline()
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    event = {'text': raw.decode('utf-8', errors='replace')}
                if relative.endswith('logs/agent/codex-rpc.ndjson'):
                    from .codex import envelope

                    event = envelope(event)
                part = obj(event.get('part'))
                state = obj(part.get('state'))
                times = obj(state.get('time')) or obj(part.get('time'))
                recovered = event.get('source') == 'opencode-session-api'
                recorded_time = times.get('start')
                if recorded_time is None and not recovered:
                    recorded_time = event.get('timestamp')
                images = [{'sha256': sha, 'mime': mime} for sha, mime, _ in image_parts(event)]
                images = list({item['sha256']: item for item in images}.values())
                kind = event.get(
                    'type', 'tool' if event.get('tool') else 'assertion' if event.get('assertion') else 'record'
                )
                title = part.get('tool') or event.get('tool') or event.get('operation') or kind.replace('_', ' ')
                values.append(
                    {
                        'id': f'{relative}:{entry["revisions"][0]["line"]}',
                        'sequence': position + 1,
                        'source': relative,
                        'line': entry['line'],
                        'revisions': [r['line'] for r in entry['revisions']],
                        'kind': kind,
                        'title': title,
                        'status': state.get('status'),
                        'time': recorded_time,
                        'recovered': recovered,
                        'recovery_time': event.get('timestamp') if recovered else None,
                        'time_basis': (
                            'part time' if times.get('start') is not None else 'unknown' if recovered else 'event time'
                        ),
                        'call_id': part.get('callID'),
                        'message_id': part.get('messageID'),
                        'input': display_value(state.get('input', event.get('arguments'))),
                        'output': display_value(state.get('output', part.get('text', event.get('text')))),
                        'error': state.get('error') or obj(event.get('failure')).get('message') or entry['error'],
                        'images': images,
                        'record': display_value(event),
                    }
                )
                if relative.endswith('logs/agent/codex-rpc.ndjson'):
                    from .codex import presentation

                    values[-1].update({k: display_value(v) for k, v in presentation(event).items()})
        return {
            'version': VERSION,
            'events': values,
            'total': len(entries),
            'offset': offset,
            'next': offset + len(values) if offset + len(values) < len(entries) else None,
            'order': 'source order; repeated part IDs coalesced, revisions retained',
        }

    def embedded_image(self, run_id, relative, line, sha):
        # Resolve directly from original record: cache eviction cannot lose evidence.
        for number, _, event, _ in self.records(run_id, relative):
            if number == line:
                for digest, mime, data in image_parts(event):
                    if digest == sha:
                        return mime, data
                break
        raise FileNotFoundError('Embedded observation not found')
