#!/usr/bin/env python3
"""Check ram101 read-only PMU state probe and retained recovery safeguards."""
import gzip
import hashlib
import json
from pathlib import Path
import stat
import subprocess

from common import BASELINE, HERE, IMAGE, ROOT, SOURCE, WORK, audit_archive, sha


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def main():
    m = json.loads((IMAGE / 'manifest.json').read_text())
    assert m['kernel'] == '6.18.48-perrier-ram101' and m['profile'] == 'pmu-probe'
    baseline = json.loads((HERE / 'working-baseline.json').read_text())
    assert baseline['display_visible_and_aligned'] and baseline['native_gen4_touch_verified']
    assert baseline['hardware_expiry_verified'] and baseline['recovery_elapsed_seconds'] >= 100
    assert sha(baseline['result']) == baseline['result_sha256']
    for item in m['artifacts'].values():
        path = Path(item['path'])
        assert sha(path) == item['sha256'] and path.stat().st_size == item['size'], path
    for item in m['inputs'].values():
        assert sha(item['path']) == item['sha256'], item['path']
    for key, path in {'rootfs_manifest_sha256': IMAGE / 'rootfs-manifest.json',
                      'initramfs_sha256': IMAGE / 'initramfs.cpio',
                      'kernel_config_sha256': IMAGE / 'kernel-build/.config',
                      'guard_sha256': IMAGE / 'rootfs/usr/sbin/ram-guard'}.items():
        assert sha(path) == m[key], key
    sources = json.loads((HERE / 'patches/manifest.json').read_text())
    tree = json.loads((HERE / 'out/source-tree-verification.json').read_text())
    assert tree['passed'] and tree['source_manifest_sha256'] == sha(HERE / 'patches/manifest.json')
    for name, record in sources['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == record['after_sha256'], name
    proof = json.loads((ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == m['guard_sha256']
    previous = ROOT / 'development/perrier-ramenv/native-diagnostics'
    a, b = config(previous / 'kernel-build/.config'), config(IMAGE / 'kernel-build/.config')
    differences = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
    assert differences == {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE'}, differences
    assert b.get('CONFIG_SMP') != 'y' and b.get('CONFIG_THUMB2_KERNEL') != 'y'
    assert b.get('CONFIG_PREEMPT_NONE') == 'y'
    for key in ('CONFIG_REGULATOR_TWL4030', 'CONFIG_REGULATOR_TWL6030',
                'CONFIG_TWL4030_MADC', 'CONFIG_TWL4030_USB',
                'CONFIG_TWL6030_USB', 'CONFIG_RTC_HCTOSYS', 'CONFIG_RTC_SYSTOHC',
                'CONFIG_RTC_NVMEM', 'CONFIG_GPIO_CDEV_V1', 'CONFIG_GPIO_TWL6040',
                'CONFIG_INPUT_TWL6040_VIBRA', 'CONFIG_SND_USB_AUDIO'):
        assert b.get(key) != 'y', key
    assert b['CONFIG_LOCALVERSION'] == '"-perrier-ram101"'
    assert b['CONFIG_INITRAMFS_SOURCE'] == '"' + str(IMAGE / 'initramfs.cpio') + '"'
    for key in ['CONFIG_OMAP_WATCHDOG', 'CONFIG_WATCHDOG_NOWAYOUT', 'CONFIG_TOUCHSCREEN_CYTTSP4']:
        assert b[key] == 'y', key
    before = json.loads((previous / 'rootfs-manifest.json').read_text())
    after = json.loads((IMAGE / 'rootfs-manifest.json').read_text())
    rootfs_changes = {'etc/init.d/rcS'}
    assert {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)} == rootfs_changes
    assert (IMAGE / 'rootfs/etc/init.d/rcS').read_bytes() == (previous / 'rootfs/etc/init.d/rcS').read_bytes().replace(b'ram100', b'ram101')
    qt = json.loads(Path(m['inputs']['qt_runtime_manifest']['path']).read_text())
    assert sha(IMAGE / 'rootfs/qt/bin/perrier-touch-grid') == qt['files']['bin/perrier-touch-grid']['sha256']
    for name, info in after.items():
        path = IMAGE / 'rootfs' / name
        if 'symlink' in info:
            assert path.is_symlink() and str(path.readlink()) == info['symlink'], name
        else:
            assert sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], name
    for name in ['etc/shadow', 'etc/dropbear/ram_host_key', 'root/.ssh/authorized_keys']:
        assert stat.S_IMODE((IMAGE / 'rootfs' / name).stat().st_mode) == 0o600
    audit_archive(IMAGE / 'initramfs.cpio', after)
    packed = (IMAGE / 'kernel-build/usr/initramfs_inc_data').read_bytes()
    assert gzip.decompress(packed) == (IMAGE / 'initramfs.cpio').read_bytes()
    assert packed in (IMAGE / 'kernel-build/vmlinux').read_bytes()
    from audit_diagnostics import audit_diagnostics
    dt = audit_diagnostics(IMAGE / 'board.dtb')
    peripherals = dt
    old_sources = json.loads((HERE / 'baselines/ram100/patches/manifest.json').read_text())
    changed = {name for name in sources['files'] if sources['files'][name] != old_sources['files'].get(name)}
    assert changed == {'arch/arm/mach-omap2/io.c', 'arch/arm/mach-omap2/perrier-pmu-probe.h'}, changed
    assert set(sources['files']) - set(old_sources['files']) == {'arch/arm/mach-omap2/perrier-pmu-probe.h'}
    assert sha(IMAGE / 'board.dtb') == sha(previous / 'board.dtb')
    source = (SOURCE / 'arch/arm/mach-omap2/io.c').read_text()
    probe = source[source.index('/* Temporary, read-only RAM probe;'):source.index('late_initcall(perrier_pmu_read_security);')]
    assert 'mcr p' not in probe.lower() and 'writel' not in probe
    assert probe.count('mrc p15') == 2 and probe.count('mrc p14') == 1
    for name in ('drivers/iio/adc/twl6030-gpadc.c', 'drivers/perf/arm_pmu.c',
                 'drivers/perf/arm_pmu_platform.c', 'drivers/perf/arm_v7_pmu.c'):
        assert name not in sources['files']
    symbols = (IMAGE / 'kernel-build/System.map').read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    result = dict(m, passed=True, kernel_span_bytes=image_end - 0xc0000000,
                  dt_audit=dt, peripheral_audit=peripherals, unchanged_display_audio_input_reuse_ram100_checks=True, bounded_probe_reads_only=True, native_diagnostics_drivers_unmodified=True, rootfs_changes=sorted(rootfs_changes),
                  sources_apply_to_pristine_linux=True, embedded_initramfs_verified=True,
                  previous_physical_baseline=str(HERE / 'working-baseline.json'))
    (IMAGE / 'reviewed-image.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': m['kernel'], 'dt_audit': dt}, indent=2))


if __name__ == '__main__':
    main()
