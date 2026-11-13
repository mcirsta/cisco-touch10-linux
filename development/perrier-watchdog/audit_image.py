#!/usr/bin/env python3
"""Review ram59 against the working ram58; permit only watchdog additions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy
import stat
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RAM = ROOT / 'development/perrier-ramenv'
BASE = RAM / 'native-thermal'
DEST = RAM / 'native-watchdog'
fdt_nodes = runpy.run_path(str(ROOT / 'development/perrier-simpledrm/audit.py'))['fdt_nodes']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def audit_fdt():
    before = fdt_nodes((BASE / 'board.dtb').read_bytes())
    after = fdt_nodes((DEST / 'board.dtb').read_bytes())
    target = '/target-module@4a314000'
    child = target + '/watchdog@0'
    assert set(after) - set(before) == {target, child}
    assert not set(before) - set(after)
    handles = {struct.unpack('>I', props['phandle'])[0]:
               struct.unpack('>I', after[path]['phandle'])[0]
               for path, props in before.items()
               if 'phandle' in props and 'phandle' in after[path]}
    for path, old in before.items():
        new = after[path]
        # Adding the first consumer may assign a previously unused provider a phandle.
        assert set(new) - set(old) <= {'phandle'}, (path, set(new) - set(old))
        assert not set(old) - set(new), (path, set(old) - set(new))
        for key, a in old.items():
            b = new[key]
            if a == b:
                continue
            assert len(a) == len(b) and len(a) % 4 == 0, (path, key)
            old_cells = struct.unpack('>' + 'I' * (len(a) // 4), a)
            new_cells = struct.unpack('>' + 'I' * (len(b) // 4), b)
            assert all(x == y or handles.get(x) == y
                       for x, y in zip(old_cells, new_cells)), (path, key)
    props = after[target]
    assert props['compatible'] == b'ti,sysc-omap2\0ti,sysc\0'
    assert props['reg'] == struct.pack('>IIIIII', 0x4a314000, 4, 0x4a314010, 4, 0x4a314014, 4)
    assert props['ranges'] == struct.pack('>III', 0, 0x4a314000, 0x1000)
    assert props['ti,sysc-mask'] == struct.pack('>I', 0x22)
    assert props['ti,syss-mask'] == struct.pack('>I', 1)
    assert props['ti,sysc-sidle'] == struct.pack('>IIII', 0, 1, 2, 3)
    assert 'ti,no-reset-on-init' in props and 'ti,no-idle-on-init' in props
    clock = '/ocp/interconnect@4a300000/segment@0/target-module@6000/prm@0/l4_wkup_cm@1800/clk@20'
    assert props['clocks'] == after[clock]['phandle'] + struct.pack('>II', 0x10, 0)
    assert props['clock-names'] == b'fck\0'
    assert set(after[child]) == {'compatible', 'reg', 'interrupts', 'timeout-sec'}
    assert after[child]['compatible'] == b'ti,omap4-wdt\0ti,omap3-wdt\0'
    assert after[child]['reg'] == struct.pack('>II', 0, 0x80)
    assert after[child]['interrupts'] == struct.pack('>III', 0, 80, 4)
    assert after[child]['timeout-sec'] == struct.pack('>I', 120)
    assert after['/ocp']['status'] == b'disabled\0'
    return {'new_nodes': [target, child], 'other_hardware_properties_unchanged': True}


def audit_archive(entries):
    data = (DEST / 'initramfs.cpio').read_bytes()
    pos = 0
    packed = set()
    seen = set()
    while True:
        assert data[pos:pos + 6] == b'070701'
        fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = data[pos + 110:pos + 110 + namesize - 1].decode()
        start = (pos + 110 + namesize + 3) & ~3
        payload = data[start:start + size]
        pos = (start + size + 3) & ~3
        assert name not in seen, name
        seen.add(name)
        if name == 'TRAILER!!!':
            break
        if stat.S_ISREG(mode):
            assert hashlib.sha256(payload).hexdigest() == entries[name]['sha256'], name
            packed.add(name)
        elif stat.S_ISLNK(mode):
            assert payload.decode() == entries[name]['symlink'], name
            packed.add(name)
        elif stat.S_ISCHR(mode):
            assert (name, fields[9], fields[10]) in {('dev/console', 5, 1), ('dev/null', 1, 3)}
        else:
            assert stat.S_ISDIR(mode), name
    assert packed == set(entries)


def main():
    manifest = json.loads((DEST / 'manifest.json').read_text())
    assert manifest['kernel'] == '6.18.48-perrier-ram59'
    assert manifest['profile'] == 'native-watchdog'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    for info in manifest['inputs'].values():
        assert sha(Path(info['path'])) == info['sha256'], info['path']
    for key, path in {'initramfs_sha256': DEST / 'initramfs.cpio',
                      'kernel_config_sha256': DEST / 'kernel-build/.config',
                      'rootfs_manifest_sha256': DEST / 'rootfs-manifest.json',
                      'guard_sha256': DEST / 'rootfs/usr/sbin/ram-guard'}.items():
        assert sha(path) == manifest[key], key
    baseline = json.loads((BASE / 'reviewed-image.json').read_text())
    assert baseline['passed'] and baseline['kernel'] == '6.18.48-perrier-ram58'
    for name in ('native_patch_manifest', 'touch_patch_manifest'):
        info = manifest['inputs'][name]
        base = Path(info['path']).parent
        for item in json.loads(Path(info['path']).read_text())['patches']:
            assert sha(base / item['patch']) == item['patch_sha256']
            assert sha(ROOT / 'development/sources/linux-6.18.48' / item['path']) == item['patched_sha256']
    old = config(BASE / 'kernel-build/.config')
    new = config(DEST / 'kernel-build/.config')
    changes = {key: [old.get(key), new.get(key)] for key in old.keys() | new.keys()
               if old.get(key) != new.get(key)}
    expected = {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE', 'CONFIG_CMDLINE',
                'CONFIG_WATCHDOG', 'CONFIG_WATCHDOG_CORE', 'CONFIG_WATCHDOG_NOWAYOUT',
                'CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED', 'CONFIG_WATCHDOG_OPEN_TIMEOUT',
                'CONFIG_WATCHDOG_SYSFS', 'CONFIG_OMAP_WATCHDOG'}
    assert set(changes) == expected, changes
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram59"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(DEST / 'initramfs.cpio') + '"'
    assert new['CONFIG_CMDLINE'] == old['CONFIG_CMDLINE'][:-1] + ' omap_wdt.early_enable=1 omap_wdt.timer_margin=120"'
    for key in expected - {'CONFIG_LOCALVERSION', 'CONFIG_INITRAMFS_SOURCE', 'CONFIG_CMDLINE',
                           'CONFIG_WATCHDOG_OPEN_TIMEOUT'}:
        assert new[key] == 'y', key
    assert new['CONFIG_WATCHDOG_OPEN_TIMEOUT'] == '60'
    for key in ('CONFIG_CPU_FREQ', 'CONFIG_CPU_IDLE', 'CONFIG_SMP', 'CONFIG_SUSPEND',
                'CONFIG_MODULES', 'CONFIG_PINCTRL_SINGLE', 'CONFIG_SOFT_WATCHDOG'):
        assert new.get(key) != 'y', key
    dt = audit_fdt()
    before = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after = json.loads((DEST / 'rootfs-manifest.json').read_text())
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    assert changed == {'etc/init.d/rcS', 'usr/sbin/ram-guard'}, changed
    for name, info in after.items():
        path = DEST / 'rootfs' / name
        if 'symlink' in info:
            assert path.is_symlink() and str(path.readlink()) == info['symlink'], name
        else:
            assert sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], name
    for name in ('etc/shadow', 'etc/dropbear/ram_host_key', 'root/.ssh/authorized_keys'):
        assert stat.S_IMODE((DEST / 'rootfs' / name).stat().st_mode) == 0o600, name
    for name in ('etc/init.d/rcS', 'usr/bin/qt-run'):
        subprocess.run(['sh', '-n', DEST / 'rootfs' / name], check=True)
    audit_archive(after)
    rejection = subprocess.run(['qemu-arm', '-cpu', 'cortex-a9', DEST / 'ram-guard', 'daemon'],
                               capture_output=True, text=True, timeout=5)
    assert rejection.returncode == 1 and 'wrong board' in rejection.stderr
    image_end = next(int(line.split()[0], 16) for line in
                     (DEST / 'kernel-build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report = dict(manifest, passed=True, kernel_span_bytes=image_end - 0xc0000000,
                  config_changes=changes, rootfs_changes=sorted(changed), dt_audit=dt,
                  watchdog_backend='linux-watchdog', hardware_expiry_proven=False,
                  purpose='Cold-start OMAP WDT2 through mainline driver with bounded host lease')
    (DEST / 'reviewed-image.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': report['kernel'],
                      'kernel_span_bytes': report['kernel_span_bytes'],
                      'config_changes': sorted(changes), 'dt_audit': dt}, indent=2))


if __name__ == '__main__':
    main()
