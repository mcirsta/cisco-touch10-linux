#!/usr/bin/env python3
"""Prepare one audited U-Boot RAM attempt with a fresh one-use RNG seed."""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'development/perrier-ramenv/native-watchdog'
OUT = DEST / 'uboot'
P8 = ROOT / 'development/perrier-coldboot/stock-p8-before.bin'
sys.path.insert(0, str(ROOT / 'tools'))
import touch10_dev as dev
from touch10_ram import seeded_board_dtb
from build_console_env_candidate import (SIGNED_UBOOT, SIGNED_SHA256, UBOOT_CODE,
                                         CODE_OFFSET, parse_entries, encode_image)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    global DEST, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('native-watchdog', 'cold-ethernet', 'gen4-touch', 'mainline-ram', 'mainline-bus', 'display-dispc', 'display-pll', 'display-pll-only', 'display-onoff', 'display-align', 'dsi-hsync', 'dsi-late-video', 'dsi-standard-video', 'dsi-exact-lines', 'dsi-command-clock', 'bridge-regmap', 'bridge-reset', 'dsi-mainline-hbp'), default='native-watchdog')
    args = parser.parse_args()
    DEST = ROOT / 'development/perrier-ramenv' / args.profile
    OUT = DEST / 'uboot'
    version = {'native-watchdog': 'ram59', 'cold-ethernet': 'ram60', 'gen4-touch': 'ram64', 'mainline-ram': 'ram65', 'mainline-bus': 'ram66', 'display-dispc': 'ram67', 'display-pll': 'ram68', 'display-pll-only': 'ram69', 'display-onoff': 'ram70', 'display-align': 'ram71', 'dsi-hsync': 'ram72', 'dsi-late-video': 'ram73', 'dsi-standard-video': 'ram74', 'dsi-exact-lines': 'ram75', 'dsi-command-clock': 'ram76', 'bridge-regmap': 'ram77', 'bridge-reset': 'ram78', 'dsi-mainline-hbp': 'ram79'}[args.profile]
    review_path = DEST / 'reviewed-image.json'
    proof_path = ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json'
    review = json.loads(review_path.read_text())
    proof = json.loads(proof_path.read_text())
    if not review['passed'] or review['kernel'] != '6.18.48-perrier-' + version or \
       proof['status'] != 'passed' or proof['guard_sha256'] != review['guard_sha256'] or \
       proof['profile'] != 'native-watchdog' or not proof['stock_recovered']:
        raise ValueError('The exact watchdog feeder needs a passing hardware-expiry proof')
    validation = None
    if args.profile == 'cold-ethernet' and (DEST / 'kexec-validation.json').exists():
        validation_path = DEST / 'kexec-validation.json'
        record = json.loads(validation_path.read_text())
        trial = json.loads(Path(record['result']).read_text())
        # Historical bring-up evidence is optional. Future kernel builds go
        # directly to the audited one-shot U-Boot route without a kexec gate.
        if trial['status'] == 'passed' and trial['ram']['kernel'] == review['kernel'] and \
           trial['artifacts'] == review['artifacts'] and trial['stock_recovered'] and \
           trial['environment_after'] == dev.STOCK_ENV_SHA256:
            validation = record
    for item in review['artifacts'].values():
        path = Path(item['path'])
        if sha(path.read_bytes()) != item['sha256']:
            raise ValueError('An audited RAM artifact changed')
    original = P8.read_bytes()
    if len(original) != 262144 or sha(original) != dev.STOCK_ENV_SHA256 or \
       struct.unpack_from('<I', original)[0] != zlib.crc32(original[4:]) & 0xffffffff:
        raise ValueError('The factory p8 baseline changed')
    entries = parse_entries(original[4:])
    current = dict(entries)
    signed, code = SIGNED_UBOOT.read_bytes(), UBOOT_CODE.read_bytes()
    if sha(signed) != SIGNED_SHA256 or signed[CODE_OFFSET:] != code:
        raise ValueError('The installed-version U-Boot reference changed')
    start = code.index(b'bootcmd=')
    end = code.index(b'\0\0', start)
    factory = dict(parse_entries(code[start:end + 2]))
    if len(entries) != 30 or current['bootcmd'] != 'run normalboot' or \
       current['normalboot'] != factory['bootcmd'] or current['autoupgrade'] != '0' or \
       'bootdelay' in current:
        raise ValueError('The environment is not the reviewed normal-boot state')
    OUT.mkdir(mode=0o700, exist_ok=True)
    seeded_path = OUT / 'board-seeded.dtb'
    seeded_board_dtb(Path(review['artifacts']['board.dtb']['path']), seeded_path)
    sources = {'zImage': Path(review['artifacts']['zImage']['path']), 'board.dtb': seeded_path}
    addresses = {'zImage': 0x84000000, 'board.dtb': 0x83000000}
    ranges = [(0x80000000, 0x80000000 + review['kernel_span_bytes'], 'uncompressed kernel')]
    files = {}
    for name, path in sources.items():
        data = path.read_bytes()
        checksum = sha(data)
        extension = 'zImage' if name == 'zImage' else 'dtb'
        files[name] = {'source': str(path.relative_to(ROOT)),
                       'target': f'/touch10-dev/{version}-{checksum[:12]}.{extension}',
                       'bytes': len(data), 'sha256': checksum,
                       'load_address': f'0x{addresses[name]:08x}'}
        ranges.append((addresses[name], addresses[name] + len(data), name))
    if struct.unpack_from('<I', sources['zImage'].read_bytes(), 0x24)[0] != 0x016f2818:
        raise ValueError('Not an ARM zImage')
    for index, (start, end, name) in enumerate(ranges):
        if not 0x80000000 <= start < end <= 0x99000000:
            raise ValueError(name + ' leaves the reviewed low-memory span')
        for a, b, other in ranges[index + 1:]:
            if max(start, a) < min(end, b):
                raise ValueError(name + ' overlaps ' + other)
    kernel, fdt = files['zImage'], files['board.dtb']
    test = (f'if ext4load mmc 1:e {kernel["load_address"]} {kernel["target"]}; then '
            f'if ext4load mmc 1:e {fdt["load_address"]} {fdt["target"]}; then '
            f'bootz {kernel["load_address"]} - {fdt["load_address"]}; fi; fi')
    command = ('if setenv bootcmd run normalboot; then '
               'if saveenv; then echo PERRIER_ONESHOT_SAVED; ' + test +
               '; fi; fi; run normalboot')
    candidate = encode_image([(key, command if key == 'bootcmd' else value) for key, value in entries])
    path = OUT / 'oneshot-p8.bin'
    path.write_bytes(candidate)
    path.chmod(0o600)
    manifest = {'profile': args.profile, 'kernel': review['kernel'],
                'source_p8': str(P8.relative_to(ROOT)), 'source_p8_sha256': sha(original),
                'candidate_bytes': len(candidate), 'candidate_p8_sha256': sha(candidate),
                'candidate_p8_crc32': f'{struct.unpack_from("<I", candidate)[0]:08x}',
                'image_review_sha256': sha(review_path.read_bytes()),
                'watchdog_proof_sha256': sha(proof_path.read_bytes()),
                'guard_sha256': review['guard_sha256'], 'bootcmd': command,
                'test_command': test, 'test_files': files, 'ranges': ranges,
                'rng_seed': 'fresh host getrandom(64), one use per manifest',
                'factory_next_boot': 'U-Boot saves normalboot before loading the candidate'}
    if validation is not None:
        manifest['kexec_validation'] = {'path': str(validation_path.relative_to(ROOT)),
                                        'sha256': sha(validation_path.read_bytes())}
    (OUT / 'oneshot-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'prepared': True, 'kernel': review['kernel'],
                      'candidate_p8_sha256': sha(candidate), 'test_files': files}, indent=2))


if __name__ == '__main__':
    main()
