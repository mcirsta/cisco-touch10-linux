#!/usr/bin/env python3
"""Independently review the one-shot U-Boot p8 image and its boot artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
from build_console_env_candidate import parse_entries  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entries(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    if len(data) != 262144 or struct.unpack_from('<I', data)[0] != zlib.crc32(data[4:]) & 0xffffffff:
        raise ValueError('Invalid p8 size or CRC')
    return dict(parse_entries(data[4:]))


def main() -> None:
    manifest_path = HERE / 'oneshot-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    before = entries(HERE / 'stock-p8-before.bin')
    after = entries(HERE / 'oneshot-p8.bin')
    if sha((HERE / 'stock-p8-before.bin').read_bytes()) != manifest['source_p8_sha256'] or \
       sha((HERE / 'oneshot-p8.bin').read_bytes()) != manifest['candidate_p8_sha256']:
        raise ValueError('Environment hash mismatch')
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    if changed != {'bootcmd'} or \
       before['bootcmd'] != 'run normalboot' or \
       after['normalboot'] != before['normalboot'] or \
       after['bootcmd'] != manifest['bootcmd']:
        raise ValueError('Unexpected U-Boot variable change')
    paths = []
    for name in ('zImage', 'board.dtb'):
        item = manifest['test_files'][name]
        content = (ROOT / item['source']).read_bytes()
        if len(content) != item['bytes'] or sha(content) != item['sha256']:
            raise ValueError(f'{name} changed after candidate construction')
        if not re.fullmatch(r'/touch10-dev/cold01-[0-9a-f]{12}\.(?:zImage|dtb)', item['target']):
            raise ValueError('Unsafe U-Boot staging path')
        paths.append(item['target'])
    kernel, fdt = (manifest['test_files'][name] for name in ('zImage', 'board.dtb'))
    expected_test = (f'if ext4load mmc 1:e {kernel["load_address"]} {kernel["target"]}; then '
                     f'if ext4load mmc 1:e {fdt["load_address"]} {fdt["target"]}; then '
                     f'bootz {kernel["load_address"]} - {fdt["load_address"]}; fi; fi')
    expected_cmd = ('if setenv bootcmd run normalboot; then '
                    'if saveenv; then echo PERRIER_ONESHOT_SAVED; '
                    + expected_test + '; fi; fi; run normalboot')
    if after['bootcmd'] != expected_cmd or manifest['test_command'] != expected_test or \
       'bootdelay' in after or len(set(paths)) != 2:
        raise ValueError('Unexpected load path, address or boot command')
    if manifest['candidate_bytes'] != 262144 or \
       manifest['candidate_p8_crc32'] != f'{struct.unpack_from("<I", (HERE / "oneshot-p8.bin").read_bytes())[0]:08x}':
        raise ValueError('Manifest size or CRC mismatch')
    probe = json.loads((HERE / 'probe-audit.json').read_text())
    if not probe['passed'] or probe['kernel'] != '6.18.48-perrier-cold01':
        raise ValueError('Probe audit missing')
    report = {
        'passed': True,
        'candidate_p8_sha256': manifest['candidate_p8_sha256'],
        'source_p8_sha256': manifest['source_p8_sha256'],
        'manifest_sha256': sha(manifest_path.read_bytes()),
        'changed_environment_variables': sorted(changed),
        'test_files': manifest['test_files'],
        'factory_next_boot_requires_saveenv': True,
        'uboot_saveenv_writes_p8_before_test': True,
        'test_kernel_has_no_storage_driver': True,
        'cold_hang_needs_manual_power_cycle_if_watchdog_inactive': True,
    }
    (HERE / 'oneshot-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
