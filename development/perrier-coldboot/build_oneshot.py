#!/usr/bin/env python3
"""Build an audited, one-boot U-Boot environment from the live p8 snapshot.

Offline only: this program never connects to or writes the Touch 10.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
from build_console_env_candidate import (  # noqa: E402
    SIGNED_SHA256, SIGNED_UBOOT, UBOOT_CODE, CODE_OFFSET,
    encode_image, parse_entries,
)

STOCK_P8_SHA256 = 'f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad'
BASE = HERE
P8 = HERE / 'stock-p8-before.bin'
OUT = HERE / 'oneshot-p8.bin'
MANIFEST = HERE / 'oneshot-manifest.json'
KERNEL_ADDR = 0x84000000
FDT_ADDR = 0x83000000
RAM_START = 0x80000000
RAM_END = 0x99000000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    original = P8.read_bytes()
    if len(original) != 0x40000 or sha(original) != STOCK_P8_SHA256:
        raise ValueError('The input must be the exact known-good current p8 snapshot')
    if struct.unpack_from('<I', original)[0] != zlib.crc32(original[4:]) & 0xffffffff:
        raise ValueError('Current U-Boot environment CRC is invalid')
    entries = parse_entries(original[4:])
    current = dict(entries)
    if len(entries) != 30 or current.get('bootcmd') != 'run normalboot':
        raise ValueError('Unexpected current U-Boot environment')
    if current.get('autoupgrade') != '0' or current.get('diag_booting') != '0':
        raise ValueError('Unexpected upgrade or diagnostic boot selector')
    if 'bootdelay' in current:
        raise ValueError('Unexpected pre-existing boot override')

    signed = SIGNED_UBOOT.read_bytes()
    code = UBOOT_CODE.read_bytes()
    if sha(signed) != SIGNED_SHA256 or signed[CODE_OFFSET:] != code:
        raise ValueError('The exact installed-version signed U-Boot reference changed')
    start = code.find(b'bootcmd=')
    end = code.find(b'\0\0', start)
    if start < 0 or end < 0:
        raise ValueError('Compiled factory boot command not found')
    factory = dict(parse_entries(code[start:end + 2]))
    if current['normalboot'] != factory['bootcmd']:
        raise ValueError('The saved normalboot command does not match compiled factory U-Boot')

    reviewed = json.loads((HERE / 'probe-audit.json').read_text())
    probe = json.loads((HERE / 'probe-manifest.json').read_text())
    if not reviewed['passed'] or reviewed['kernel'] != '6.18.48-perrier-cold01' or \
       reviewed['manifest_sha256'] != sha((HERE / 'probe-manifest.json').read_bytes()):
        raise ValueError('The serial-only cold-boot probe is not audited')
    kernel_path_host = ROOT / probe['artifacts']['zImage']['path']
    fdt_path_host = ROOT / probe['artifacts']['board.dtb']['path']
    kernel = kernel_path_host.read_bytes()
    fdt = fdt_path_host.read_bytes()
    if sha(kernel) != probe['artifacts']['zImage']['sha256'] or \
       sha(fdt) != probe['artifacts']['board.dtb']['sha256']:
        raise ValueError('The reviewed kernel or board DTB changed')
    if struct.unpack_from('<I', kernel, 0x24)[0] != 0x016f2818:
        raise ValueError('The kernel is not an ARM zImage')
    if struct.unpack_from('>I', fdt)[0] != 0xd00dfeed:
        raise ValueError('The board file is not a flattened device tree')
    baseline = json.loads((ROOT / 'development/perrier/baselines/ram01/reviewed-trial.json').read_text())
    if baseline['memory_start'] != RAM_START or baseline['memory_size'] != RAM_END - RAM_START:
        raise ValueError('Reviewed low-memory span changed')
    uncompressed_end = int(reviewed['decompressed_kernel_bss_end'], 16)
    ranges = [(RAM_START, uncompressed_end, 'uncompressed kernel'),
              (KERNEL_ADDR, KERNEL_ADDR + len(kernel), 'zImage'),
              (FDT_ADDR, FDT_ADDR + len(fdt), 'board DTB')]
    for start, end, name in ranges:
        if not RAM_START <= start < end <= RAM_END:
            raise ValueError(f'{name} is outside the reviewed low-memory range')
    for i, (start, end, name) in enumerate(ranges):
        for other_start, other_end, other in ranges[i + 1:]:
            if max(start, other_start) < min(end, other_end):
                raise ValueError(f'{name} overlaps {other}')

    kernel_name = f'cold01-{sha(kernel)[:12]}.zImage'
    fdt_name = f'cold01-{sha(fdt)[:12]}.dtb'
    kernel_path = '/touch10-dev/' + kernel_name
    fdt_path = '/touch10-dev/' + fdt_name
    test_command = (
        f'if ext4load mmc 1:e 0x{KERNEL_ADDR:x} {kernel_path}; then '
        f'if ext4load mmc 1:e 0x{FDT_ADDR:x} {fdt_path}; then '
        f'bootz 0x{KERNEL_ADDR:x} - 0x{FDT_ADDR:x}; fi; fi'
    )
    # Restore and save the factory boot path *before* loading new code.
    # Every failure branch and a returning bootz fall through to normalboot.
    bootcmd = (
        'if setenv bootcmd run normalboot; then '
        'if saveenv; then echo PERRIER_ONESHOT_SAVED; '
        + test_command + '; fi; fi; run normalboot'
    )
    candidate = [(key, bootcmd if key == 'bootcmd' else value)
                 for key, value in entries]
    expected = dict(candidate)
    encoded = encode_image(candidate)
    if len(encoded) != len(original) or \
       struct.unpack_from('<I', encoded)[0] != zlib.crc32(encoded[4:]) & 0xffffffff or \
       dict(parse_entries(encoded[4:])) != expected:
        raise ValueError('Candidate U-Boot environment did not round-trip')
    if expected['normalboot'] != current['normalboot'] or expected['bootcmd'] == current['bootcmd']:
        raise ValueError('Factory boot fallback was not preserved')

    OUT.write_bytes(encoded)
    OUT.chmod(0o600)
    manifest = {
        'status': 'prepared-offline; not staged or flashed by this builder',
        'source_p8_sha256': sha(original),
        'candidate_p8_sha256': sha(encoded),
        'candidate_p8_crc32': f'{struct.unpack_from("<I", encoded)[0]:08x}',
        'candidate_bytes': len(encoded),
        'bootcmd': bootcmd,
        'test_command': test_command,
        'factory_bootcmd_sha256': sha(current['normalboot'].encode()),
        'factory_bootcmd_preserved': True,
        'test_files': {
            'zImage': {'source': str(kernel_path_host.relative_to(ROOT)),
                       'target': kernel_path, 'bytes': len(kernel), 'sha256': sha(kernel),
                       'load_address': f'0x{KERNEL_ADDR:08x}'},
            'board.dtb': {'source': str(fdt_path_host.relative_to(ROOT)),
                          'target': fdt_path, 'bytes': len(fdt), 'sha256': sha(fdt),
                          'load_address': f'0x{FDT_ADDR:08x}'},
        },
        'decompressed_kernel_bss_end': f'0x{uncompressed_end:08x}',
        'normal_boot_on_next_reset': 'U-Boot saveenv must succeed before testboot',
        'hang_recovery': 'cold power cycle may be required if no watchdog is running',
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in
                      ('status', 'source_p8_sha256', 'candidate_p8_sha256',
                       'candidate_p8_crc32', 'candidate_bytes', 'test_files')}, indent=2))


if __name__ == '__main__':
    main()
