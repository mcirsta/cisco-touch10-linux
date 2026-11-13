#!/usr/bin/env python3
"""Independently audit a one-use U-Boot RAM environment and load ranges."""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import runpy
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'development/perrier-ramenv/native-watchdog'
OUT = DEST / 'uboot'
sys.path.insert(0, str(ROOT / 'tools'))
from build_console_env_candidate import parse_entries
import touch10_dev as dev


def sha(data):
    return hashlib.sha256(data).hexdigest()


def env(data):
    assert len(data) == 262144
    assert struct.unpack_from('<I', data)[0] == zlib.crc32(data[4:]) & 0xffffffff
    entries = parse_entries(data[4:])
    assert len(entries) == len(dict(entries)) == 30
    return dict(entries)


def main():
    global DEST, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('native-watchdog', 'cold-ethernet', 'gen4-touch', 'mainline-ram', 'mainline-bus', 'display-dispc', 'display-pll', 'display-pll-only', 'display-onoff', 'display-align', 'dsi-hsync', 'dsi-late-video', 'dsi-standard-video', 'dsi-exact-lines', 'dsi-command-clock', 'bridge-regmap', 'bridge-reset', 'dsi-mainline-hbp', 'dsi-mainline-porches', 'dsi-mainline-pads', 'bridge-clock-order', 'display-hbp', 'display-porches', 'display-pads', 'display-sync-align', 'display-core-fck', 'display-mainline-sync', 'display-stop-trace', 'display-stop-fix', 'native-leds', 'peripherals', 'rtc-gpio', 'native-audio', 'application-audio', 'speaker-audio', 'native-diagnostics', 'pmu-probe', 'pmu-selftest', 'mailbox-audio', 'mailbox-audio-dt'), default='native-watchdog')
    args = parser.parse_args()
    DEST = ROOT / 'development/perrier-ramenv' / args.profile
    OUT = DEST / 'uboot'
    version = {'native-watchdog': 'ram59', 'cold-ethernet': 'ram60', 'gen4-touch': 'ram64', 'mainline-ram': 'ram65', 'mainline-bus': 'ram66', 'display-dispc': 'ram67', 'display-pll': 'ram68', 'display-pll-only': 'ram69', 'display-onoff': 'ram70', 'display-align': 'ram71', 'dsi-hsync': 'ram72', 'dsi-late-video': 'ram73', 'dsi-standard-video': 'ram74', 'dsi-exact-lines': 'ram75', 'dsi-command-clock': 'ram76', 'bridge-regmap': 'ram77', 'bridge-reset': 'ram78', 'dsi-mainline-hbp': 'ram79', 'dsi-mainline-porches': 'ram80', 'dsi-mainline-pads': 'ram81', 'bridge-clock-order': 'ram85', 'display-hbp': 'ram86', 'display-porches': 'ram87', 'display-pads': 'ram88', 'display-sync-align': 'ram89', 'display-core-fck': 'ram90', 'display-mainline-sync': 'ram91', 'display-stop-trace': 'ram92', 'display-stop-fix': 'ram93', 'native-leds': 'ram94', 'peripherals': 'ram95', 'rtc-gpio': 'ram96', 'native-audio': 'ram97', 'application-audio': 'ram98', 'speaker-audio': 'ram99', 'native-diagnostics': 'ram100', 'pmu-probe': 'ram101', 'pmu-selftest': 'ram102', 'mailbox-audio': 'ram103', 'mailbox-audio-dt': 'ram104'}[args.profile]
    manifest_path = OUT / 'oneshot-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['profile'] == args.profile
    assert manifest['kernel'] == '6.18.48-perrier-' + version
    original_path = ROOT / 'development/perrier-coldboot/stock-p8-before.bin'
    assert manifest['source_p8'] == str(original_path.relative_to(ROOT))
    original = original_path.read_bytes()
    candidate = (OUT / 'oneshot-p8.bin').read_bytes()
    assert sha(original) == manifest['source_p8_sha256'] == dev.STOCK_ENV_SHA256
    assert sha(candidate) == manifest['candidate_p8_sha256']
    assert manifest['candidate_bytes'] == len(candidate)
    assert manifest['candidate_p8_crc32'] == f'{struct.unpack_from("<I", candidate)[0]:08x}'
    before, after = env(original), env(candidate)
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    assert changed == {'bootcmd'}
    assert before['bootcmd'] == 'run normalboot'
    assert sha(before['normalboot'].encode()) == 'b6331f61bddb912d874518713df0dffb6b15140f468ceea864478c2e1f272fba'
    assert after['autoupgrade'] == after['diag_booting'] == '0' and 'bootdelay' not in after
    review_path = DEST / 'reviewed-image.json'
    proof_path = ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json'
    assert sha(review_path.read_bytes()) == manifest['image_review_sha256']
    assert sha(proof_path.read_bytes()) == manifest['watchdog_proof_sha256']
    review, proof = json.loads(review_path.read_text()), json.loads(proof_path.read_text())
    assert review['passed'] and proof['status'] == 'passed' and proof['stock_recovered']
    assert proof['profile'] == 'native-watchdog'
    assert proof['guard_sha256'] == review['guard_sha256'] == manifest['guard_sha256']
    assert proof['recovery_elapsed_seconds'] >= 100
    if 'kexec_validation' in manifest:
        assert args.profile == 'cold-ethernet'
        validation_path = DEST / 'kexec-validation.json'
        assert manifest['kexec_validation'] == {'path': str(validation_path.relative_to(ROOT)),
                                               'sha256': sha(validation_path.read_bytes())}
        validation = json.loads(validation_path.read_text())
        result_path = Path(validation['result'])
        assert result_path.is_relative_to(ROOT / 'development/runs')
        trial = json.loads(result_path.read_text())
        assert trial['status'] == 'passed' and trial['profile'] == args.profile
        assert trial['ram']['kernel'] == manifest['kernel'] and trial['stock_recovered']
        assert trial['artifacts'] == review['artifacts']
        assert trial['environment_before'] == trial['environment_after'] == dev.STOCK_ENV_SHA256
    files = manifest['test_files']
    assert set(files) == {'zImage', 'board.dtb'}
    sources = {'zImage': Path(review['artifacts']['zImage']['path']), 'board.dtb': OUT / 'board-seeded.dtb'}
    addresses = {'zImage': 0x84000000, 'board.dtb': 0x83000000}
    ranges = [[0x80000000, 0x80000000 + review['kernel_span_bytes'], 'uncompressed kernel']]
    for name, path in sources.items():
        item = files[name]
        data = path.read_bytes()
        assert item['source'] == str(path.relative_to(ROOT))
        assert item['sha256'] == sha(data) and item['bytes'] == len(data)
        extension = 'zImage' if name == 'zImage' else 'dtb'
        assert item['target'] == f'/touch10-dev/{version}-{sha(data)[:12]}.{extension}'
        assert item['load_address'] == f'0x{addresses[name]:08x}'
        ranges.append([addresses[name], addresses[name] + len(data), name])
    assert files['zImage']['sha256'] == review['artifacts']['zImage']['sha256']
    assert manifest['ranges'] == ranges
    for i, (a, b, name) in enumerate(ranges):
        assert 0x80000000 <= a < b <= 0x99000000, name
        for x, y, other in ranges[i + 1:]:
            assert max(a, x) >= min(b, y), (name, other)
    parse = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']
    base_dtb = parse(Path(review['artifacts']['board.dtb']['path']).read_bytes())
    seeded_dtb = parse(sources['board.dtb'].read_bytes())
    assert set(base_dtb) == set(seeded_dtb)
    assert 'rng-seed' not in base_dtb['/chosen'] and len(seeded_dtb['/chosen']['rng-seed']) == 64
    for path, properties in base_dtb.items():
        assert properties == {key: value for key, value in seeded_dtb[path].items()
                              if not (path == '/chosen' and key == 'rng-seed')}, path
    kernel, fdt = files['zImage'], files['board.dtb']
    expected_test = (f'if ext4load mmc 1:e 0x84000000 {kernel["target"]}; then '
                     f'if ext4load mmc 1:e 0x83000000 {fdt["target"]}; then '
                     'bootz 0x84000000 - 0x83000000; fi; fi')
    expected_cmd = ('if setenv bootcmd run normalboot; then '
                    'if saveenv; then echo PERRIER_ONESHOT_SAVED; ' + expected_test +
                    '; fi; fi; run normalboot')
    assert manifest['test_command'] == expected_test
    assert after['bootcmd'] == manifest['bootcmd'] == expected_cmd
    report = {'passed': True, 'kernel': manifest['kernel'],
              'manifest_sha256': sha(manifest_path.read_bytes()),
              'candidate_p8_sha256': sha(candidate), 'changed_environment_variables': sorted(changed),
              'watchdog_expiry_proof': str(proof_path), 'watchdog_expiry_proof_sha256': sha(proof_path.read_bytes()),
              'ranges': ranges, 'factory_environment_saved_before_handoff': True,
              'ram_kernel_emmc_readonly': True, 'peripherals_from_uboot_not_yet_proven': True}
    (OUT / 'oneshot-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
