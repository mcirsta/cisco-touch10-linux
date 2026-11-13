#!/usr/bin/env python3
"""Audit the serial-only cold-boot probe before U-Boot sees it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import struct

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'development/perrier/baselines/ram01'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def config(path: Path) -> dict[str, str]:
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def cpio_entries(data: bytes) -> dict[str, tuple[int, bytes]]:
    entries = {}
    pos = 0
    while True:
        if data[pos:pos + 6] != b'070701':
            raise ValueError('Not a newc archive')
        fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16)
                  for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = data[pos + 110:pos + 110 + namesize - 1].decode()
        start = (pos + 110 + namesize + 3) & ~3
        content = data[start:start + size]
        pos = (start + size + 3) & ~3
        if name == 'TRAILER!!!':
            break
        if name in entries:
            raise ValueError('Duplicate initramfs path')
        entries[name] = (mode, content)
    if any(data[pos:]):
        raise ValueError('Nonzero data after CPIO trailer')
    return entries


def main() -> None:
    manifest_path = HERE / 'probe-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest['kernel'] != '6.18.48-perrier-cold01':
        raise ValueError('Wrong cold-boot probe version')
    for name, record in manifest['artifacts'].items():
        file = ROOT / record['path']
        if file.stat().st_size != record['bytes'] or sha(file.read_bytes()) != record['sha256']:
            raise ValueError(f'Probe artifact changed: {name}')
    fdt = (HERE / 'board.dtb').read_bytes()
    baseline = json.loads((BASE / 'reviewed-trial.json').read_text())
    if not baseline['passed'] or sha(fdt) != baseline['artifacts']['board.dtb']['sha256']:
        raise ValueError('Board DTB differs from the reviewed serial-only RAM baseline')
    if struct.unpack_from('>I', fdt)[0] != 0xd00dfeed:
        raise ValueError('Invalid FDT magic')
    cfg = config(HERE / 'kernel-build/.config')
    if cfg['CONFIG_LOCALVERSION'] != '"-perrier-cold01"' or \
       cfg['CONFIG_INITRAMFS_SOURCE'] != '"' + str(HERE / 'initramfs.cpio') + '"' or \
       cfg.get('CONFIG_CMDLINE_FORCE') != 'y' or \
       cfg.get('CONFIG_COMPAT_32BIT_TIME') != 'y' or \
       cfg.get('CONFIG_SERIAL_8250_CONSOLE') != 'y' or \
       'panic=5' not in cfg['CONFIG_CMDLINE']:
        raise ValueError('Required serial, timer or panic options are missing')
    for key in ('SMP', 'CPU_FREQ', 'WATCHDOG', 'MODULES', 'DRM', 'USB_SUPPORT',
                'MMC', 'I2C', 'SOUND', 'PINCTRL_SINGLE'):
        if cfg.get('CONFIG_' + key) == 'y':
            raise ValueError('Unexpected cold-boot peripheral: ' + key)
    kernel = (HERE / 'kernel-build/arch/arm/boot/zImage').read_bytes()
    if struct.unpack_from('<I', kernel, 0x24)[0] != 0x016f2818:
        raise ValueError('Invalid ARM zImage header')
    cpio = cpio_entries((HERE / 'initramfs.cpio').read_bytes())
    if set(cpio) != {'dev', 'proc', 'sys', 'dev/console', 'dev/null', 'init'} or \
       not stat.S_ISREG(cpio['init'][0]) or \
       cpio['init'][1] != (HERE / 'init').read_bytes():
        raise ValueError('Unexpected initramfs content')
    image_end = next(int(line.split()[0], 16) for line in
                     (HERE / 'kernel-build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    span = image_end - 0xc0000000
    if not 0 < span < 0x02000000:
        raise ValueError('Uncompressed kernel exceeds the 32 MiB staging limit')
    report = {'passed': True, 'kernel': manifest['kernel'],
              'manifest_sha256': sha(manifest_path.read_bytes()),
              'decompressed_kernel_bss_end': f'0x{0x80000000 + span:08x}',
              'kernel_span_bytes': span,
              'initramfs_entries': sorted(cpio),
              'bootargs': cfg['CONFIG_CMDLINE']}
    (HERE / 'probe-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
