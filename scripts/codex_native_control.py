#!/usr/bin/env python3
"""Actual pinned native-policy canaries, no login or model inference."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

CHILD = r'''
import hashlib,json,os,socket
from pathlib import Path
paths=['/auth-input/auth.json','/run/codex/auth.json','/run/home/canary',
       '/run/control/canary','/config/base.toml','/ipc/canary',
       '/workspace/canary','/audit/canary','/proc/self/environ',
       '/proc/self/root/auth-input/auth.json','/proc/1/root/auth-input/auth.json',
       '/dev/fd/0','/proc/self/fd/0','/session/alias-auth','/session/alias-proc']
denied={}
for name in paths:
    try:
        with open(name,'rb') as stream:stream.read(1)
        denied[name]=False
    except OSError:denied[name]=True
fd_denied=True
for fd in range(3,64):
    try:
        os.set_blocking(fd,False)
        data=os.read(fd,1024)
        if hashlib.sha256(data).hexdigest()==os.environ['CANARY_SHA256']:fd_denied=False
    except OSError:pass
try:
    sock=socket.socket();sock.settimeout(1)
    sock.connect(('127.0.0.1',38741));network_denied=False
except OSError:network_denied=True
print(json.dumps({'denied':denied,'inherited_canary_fd_denied':fd_denied,
                  'parent_loopback_denied':network_denied,
                  'positive_read':Path('/session/visible').read_text()=='public-control'}))
'''

BOOT = r'''
import ctypes,hashlib,json,os,socket,subprocess
from pathlib import Path
Path('/run/codex/config.toml').symlink_to('/config/base.toml')
marker=b'synthetic-native-auth-canary'
Path('/run/codex/auth.json').write_bytes(marker)
for name in ['/run/home/canary','/run/control/canary']:Path(name).write_bytes(marker)
listener=socket.socket();listener.bind(('127.0.0.1',38741));listener.listen()
positive=socket.create_connection(('127.0.0.1',38741));positive.close()
fd=os.open('/run/codex/auth.json',os.O_RDONLY)
os.set_inheritable(fd,True)
os.environ['CANARY_SHA256']=hashlib.sha256(marker).hexdigest()
command=['/opt/codex/bin/codex','sandbox','-P','bench','--include-managed-config',
         '--cd','/session','--','/usr/local/bin/python','-c',Path('/probe/child.py').read_text()]
# Match the trusted supervisor's boundary: credentials must never be passed as
# inherited descriptors. Path policies cannot revoke an intentionally passed FD.
result=subprocess.run(command,capture_output=True,text=True,close_fds=True,timeout=20)
os.close(fd);listener.close()
lib=ctypes.CDLL(None,use_errno=True)
ctypes.set_errno(0)
remount=lib.mount(None,b'/',None,ctypes.c_ulong(32),None)
remount_errno=ctypes.get_errno()
ctypes.set_errno(0)
unknown_unshare=lib.unshare(ctypes.c_int(0x40000000))
print(json.dumps({'native_returncode':result.returncode,'native_stdout':result.stdout,
                  'native_stderr':result.stderr,'outer_rw_remount_denied':remount==-1,
                  'outer_rw_remount_errno':remount_errno,
                  'unapproved_unshare_denied':unknown_unshare==-1,
                  'apparmor':Path('/proc/self/attr/current').read_text().strip(),
                  'status':{k:v.strip() for k,v in
                            (line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
                            if k in ['CapEff','CapBnd','NoNewPrivs','Seccomp']}}))
'''


def control():
    from gui_agent_bench.docker import client_environment, isolation, mount
    from gui_agent_bench.runners.codex_config import IMAGES
    from gui_agent_bench.runners.codex_security import options, policy

    with tempfile.TemporaryDirectory(prefix='gab-native-control-') as temp:
        root = Path(temp)
        for name in ['session', 'auth', 'ipc', 'workspace', 'audit', 'probe']:
            (root / name).mkdir()
            (root / name / 'canary').write_text('synthetic-native-auth-canary')
        (root / 'auth/auth.json').write_text('synthetic-native-auth-canary')
        (root / 'session/visible').write_text('public-control')
        (root / 'session/alias-auth').symlink_to('/auth-input/auth.json')
        (root / 'session/alias-proc').symlink_to('/proc/self/environ')
        (root / 'probe/child.py').write_text(CHILD)
        mounts = mount(ROOT / 'configs/codex', '/config')
        for name, target in [
            ('session', '/session'),
            ('auth', '/auth-input'),
            ('ipc', '/ipc'),
            ('workspace', '/workspace'),
            ('audit', '/audit'),
            ('probe', '/probe'),
        ]:
            mounts += mount(root / name, target)
        tmpfs = []
        for name, size in [('codex', '64m'), ('home', '16m'), ('control', '1m')]:
            tmpfs += [
                '--tmpfs',
                f'/run/{name}:rw,nosuid,nodev,size={size},mode=0700,uid={os.getuid()},gid={os.getgid()}',
            ]
        command = [
            'docker',
            'run',
            '--rm',
            '--network',
            'none',
            *isolation(),
            *options(),
            *tmpfs,
            *mounts,
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            '--entrypoint',
            '/usr/local/bin/python',
            IMAGES['agent'],
            '-c',
            BOOT,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=40, env=client_environment())
        report = dict(
            schema='codex-native-control-v1',
            container_policy=policy(),
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            status='failed',
            inference_started=False,
            synthetic_credentials_only=True,
        )
        if result.returncode == 0:
            outer = json.loads(result.stdout)
            report['outer'] = outer
            if outer['native_returncode'] == 0:
                native = json.loads(outer['native_stdout'])
                report['native'] = native
                if (
                    all(native['denied'].values())
                    and native['inherited_canary_fd_denied']
                    and native['parent_loopback_denied']
                    and native['positive_read']
                    and outer['outer_rw_remount_denied']
                    and outer['unapproved_unshare_denied']
                    and outer['status']
                    == {'CapEff': '0000000000000000', 'CapBnd': '0000000000000000', 'NoNewPrivs': '1', 'Seccomp': '2'}
                    and outer['apparmor'] == policy()['apparmor_profile'] + ' (enforce)'
                ):
                    report['status'] = 'passed'
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = control()
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ['status', 'inference_started']}))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
