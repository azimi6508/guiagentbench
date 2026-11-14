"""Install the pinned Linux Android SDK in .mobile/sdk; never accept SDK licenses.

Downloads about 2.4 GB of hash-pinned archives into .mobile/downloads and
extracts them (about 3.3 GB). Existing verified archives and packages are reused.
"""

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.mobile_host import host_platform, runtime_lock, device_lock
from gui_agent_bench.mobile_runtime import sha_file


def extract(archive, destination, prefix):
    """Only regular files beneath the known package prefix may be installed."""
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if sum(m.file_size for m in members) > 16_000_000_000:
            raise ValueError('SDK archive exceeds extraction budget')
        for item in members:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (
                path.is_absolute()
                or '..' in path.parts
                or '\\' in item.filename
                or not path.parts
                or path.parts[0] != prefix
                or stat.S_ISLNK(mode)
            ):
                raise ValueError('SDK archive contains an unexpected entry')
        for item in members:
            path = PurePosixPath(item.filename)
            output = destination.joinpath(*path.parts[1:])
            if item.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, output.open('xb') as target:
                    shutil.copyfileobj(source, target)
                output.chmod(0o755 if item.external_attr >> 16 & 0o111 else 0o644)


def package_metadata(directory, package, version):
    # Archived emulator releases lack package.xml. AVD Manager requires it to
    # discover the installed package, as documented by Google's archive guide.
    output = directory / 'package.xml'
    if output.exists():
        return
    root = ET.Element(
        'ns2:repository',
        {
            'xmlns:ns2': 'http://schemas.android.com/repository/android/common/02',
            'xmlns:generic': 'http://schemas.android.com/repository/android/generic/02',
            'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        },
    )
    local = ET.SubElement(root, 'localPackage', path=package)
    ET.SubElement(local, 'type-details', {'xsi:type': 'generic:genericDetailsType'})
    revision = ET.SubElement(local, 'revision')
    for name, value in zip(('major', 'minor', 'micro'), version.split('.')):
        ET.SubElement(revision, name).text = value
    ET.SubElement(local, 'display-name').text = package
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)


def main():
    # Parse first: --help must describe the installer, never start a download.
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    if host_platform() != 'linux-x86_64':
        raise ValueError('This installer is for Linux x86_64; Windows uses its existing SDK')
    lock = json.loads(runtime_lock(ROOT).read_text())
    cache = ROOT / '.mobile'
    cache.mkdir(exist_ok=True)
    with device_lock(ROOT):
        downloads, sdk = cache / 'downloads', cache / 'sdk'
        downloads.mkdir(exist_ok=True)
        sdk.mkdir(exist_ok=True)
        for name in ('home', 'android-user', 'avd'):
            (cache / name).mkdir(exist_ok=True)
        packages = {
            'command_line_tools': ('cmdline-tools/latest', 'cmdline-tools'),
            'emulator': ('emulator', 'emulator'),
            'platform_tools': ('platform-tools', 'platform-tools'),
            'system_image': ('system-images/android-36/google_apis_playstore/x86_64', 'x86_64'),
        }
        for name, (relative, prefix) in packages.items():
            entry = lock['archives'][name]
            archive = downloads / entry['url'].rsplit('/', 1)[1]
            if not archive.is_file():
                print(f"Downloading {name} from {entry['url']}", flush=True)
                urllib.request.urlretrieve(entry['url'], archive)
            if sha_file(archive) != entry['sha256']:
                raise ValueError('SDK archive hash differs: ' + name)
            destination = sdk / relative
            if not destination.exists():
                # Keep incomplete extractions distinct; never overwrite an SDK.
                with tempfile.TemporaryDirectory(prefix='sdk-stage-', dir=cache) as temp:
                    staging = Path(temp) / 'package'
                    extract(archive, staging, prefix)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    staging.rename(destination)
            for path, expected in lock['sdk_sha256'].items():
                if path.startswith(relative + '/') and sha_file(sdk / path) != expected:
                    raise ValueError('Existing SDK package differs: ' + path)
            print('Verified ' + name, flush=True)
        package_metadata(sdk / 'emulator', 'emulator', lock['emulator_version'])
        package_metadata(sdk / 'cmdline-tools/latest', 'cmdline-tools;latest', lock['command_line_tools_version'])
        print(
            'SDK installed. Review licenses with .mobile/sdk/cmdline-tools/latest/bin/sdkmanager '
            '--sdk_root=' + str(sdk) + ' --licenses before mobile_setup.py prepare.'
        )


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(f'SDK installation failed: {exc}')
