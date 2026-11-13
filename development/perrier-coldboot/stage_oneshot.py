#!/usr/bin/env python3
"""Stage audited cold-boot files under new names on p14; never touch p8."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_dev as dev  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote_bytes(panel: dev.Panel, command: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(panel.ssh + [command], input=data,
                            capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f'SSH binary transfer failed: {result.stderr.decode(errors="replace")}')
    return result.stdout


def main() -> None:
    manifest_path = HERE / 'oneshot-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    audit = json.loads((HERE / 'oneshot-audit.json').read_text())
    if not audit['passed'] or audit['manifest_sha256'] != sha(manifest_path.read_bytes()):
        raise ValueError('One-shot audit does not match the current manifest')
    if manifest['source_p8_sha256'] != dev.STOCK_ENV_SHA256:
        raise ValueError('U-Boot environment baseline changed')
    directory = HERE / ('stage-' + uuid.uuid4().hex[:8])
    directory.mkdir(mode=0o700)
    dev.validate_host(dev.host_checks())
    panel = dev.Panel(directory)
    before = panel.snapshot()
    if before['kernel'] != '3.4.113+' or before['factory_app'] != 'running' or \
       panel.env_hash() != dev.STOCK_ENV_SHA256:
        raise RuntimeError('Stock state or U-Boot environment does not match the audited baseline')
    check = panel.run('''set -eu
test "$(awk '$2 == "/mnt/base" {print $1}' /proc/mounts)" = /dev/mmcblk0p14
test "$(awk '$2 == "/mnt/base" {print $3}' /proc/mounts)" = ext4
test ! -L /mnt/base/touch10-dev
if [ ! -e /mnt/base/touch10-dev ]; then
    umask 077
    mkdir /mnt/base/touch10-dev
fi
test -d /mnt/base/touch10-dev
test ! -L /mnt/base/touch10-dev
''')
    if check.returncode:
        raise RuntimeError('p14 mount or staging directory check failed')
    files = {}
    for name, item in manifest['test_files'].items():
        local = ROOT / item['source']
        content = local.read_bytes()
        if len(content) != item['bytes'] or sha(content) != item['sha256']:
            raise ValueError(f'{name} changed after audit')
        target = '/mnt/base' + item['target']
        if not target.startswith('/mnt/base/touch10-dev/cold01-'):
            raise ValueError('Unexpected staging path')
        exists = panel.run(f'if [ -e {target} ]; then echo yes; else echo no; fi\n')
        if exists.returncode or exists.stdout.strip() not in ('yes', 'no'):
            raise RuntimeError('Cannot check staged file existence')
        if exists.stdout.strip() == 'no':
            temporary = target + '.upload-' + uuid.uuid4().hex[:8]
            remote_bytes(panel, f'umask 077; cat > {temporary}', content)
            if remote_bytes(panel, f'cat {temporary}') != content:
                panel.run(f'rm -f {temporary}\n')
                raise RuntimeError(f'{name} upload differs from local artifact')
            commit = panel.run(f'set -eu\n[ ! -e {target} ]\nchmod 600 {temporary}\n'
                               f'mv {temporary} {target}\nsync\n')
            if commit.returncode:
                raise RuntimeError(f'Could not commit staged {name}')
        if remote_bytes(panel, f'cat {target}') != content:
            raise RuntimeError(f'{name} final p14 readback differs')
        files[name] = {'path': target, 'bytes': len(content), 'sha256': sha(content)}
    after = panel.snapshot()
    if after['boot_id'] != before['boot_id'] or panel.env_hash() != dev.STOCK_ENV_SHA256:
        raise RuntimeError('Stock state changed during staging')
    report = {'status': 'staged-and-readback-verified',
              'before_boot_id': before['boot_id'],
              'factory_kernel': after['kernel'],
              'factory_app': after['factory_app'],
              'p8_sha256': dev.STOCK_ENV_SHA256,
              'oneshot_manifest_sha256': sha(manifest_path.read_bytes()),
              'files': files}
    dev.write_json(HERE / 'stage-result.json', report)
    dev.write_json(directory / 'stage-result.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
