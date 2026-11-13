#!/usr/bin/env python3
"""Audit the CPU1-present, maxcpus=1 hotplug image against validated ram108."""
import gzip
import json
from pathlib import Path
import re
import stat
import subprocess

from common import ROOT, HERE, SOURCE, WORK, audit_archive, sha

IMAGE = ROOT / 'development/perrier-ramenv/smp-hotplug'
BASE = ROOT / 'development/perrier-ramenv/smp-uboot-nosmp'


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def main():
    manifest = json.loads((IMAGE / 'manifest.json').read_text())
    base = json.loads((BASE / 'reviewed-image.json').read_text())
    assert base['passed'] and base['kernel'] == '6.18.48-perrier-ram108'
    assert manifest['kernel'] == '6.18.48-perrier-ram109'
    assert manifest['profile'] == 'smp-hotplug'
    for item in manifest['artifacts'].values():
        path = Path(item['path'])
        assert path.stat().st_size == item['size'] and sha(path) == item['sha256'], path
    for item in manifest['inputs'].values():
        assert sha(item['path']) == item['sha256'], item['path']
    for key, path in {
        'rootfs_manifest_sha256': IMAGE / 'rootfs-manifest.json',
        'initramfs_sha256': IMAGE / 'initramfs.cpio',
        'kernel_config_sha256': IMAGE / 'kernel-build/.config',
        'guard_sha256': IMAGE / 'rootfs/usr/sbin/ram-guard',
    }.items():
        assert sha(path) == manifest[key], key
    assert manifest['guard_sha256'] == base['guard_sha256']
    proof = json.loads((ROOT / 'development/perrier-ramenv/native-watchdog/watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['stock_recovered']
    assert proof['guard_sha256'] == manifest['guard_sha256']
    old_dts = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', str(BASE / 'board.dtb')],
                             capture_output=True, text=True, check=True).stdout
    new_dts = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', str(IMAGE / 'board.dtb')],
                             capture_output=True, text=True, check=True).stdout
    expected_dts, count = re.subn(r'(cpu@1\s*\{[^}]*\bstatus = )"disabled";',
                                  r'\1"okay";', old_dts, count=1)
    assert count == 1 and new_dts == expected_dts, 'DT differs beyond CPU1 status'
    assert '&{/cpus/cpu@1} { status = "disabled"; };' in \
        (SOURCE / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dts').read_text()
    assert sha(HERE / 'patches/manifest.json') == \
        sha(HERE / 'baselines/ram107/patches/manifest.json')
    patches = json.loads((HERE / 'patches/manifest.json').read_text())
    for name, item in patches['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == item['after_sha256'], name
    for name in ('drivers/net/ipv6/addrconf.c', 'net/ipv6/addrconf.c',
                 'drivers/net/usb/smsc95xx.c'):
        assert name not in patches['files'], name

    old = config(BASE / 'kernel-build/.config')
    new = config(IMAGE / 'kernel-build/.config')
    changes = {key: {'before': old.get(key, 'n'), 'after': new.get(key, 'n')}
               for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)}
    expected = json.loads((HERE / 'configs/cpu1-hotplug-config-delta.json').read_text())
    assert changes == expected, changes
    assert new['CONFIG_IPV6'] == 'y'
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram109"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(IMAGE / 'initramfs.cpio') + '"'
    for key in ('CONFIG_CPU_FREQ', 'CONFIG_REGULATOR_TWL4030',
                'CONFIG_REGULATOR_TWL6030', 'CONFIG_REMOTEPROC',
                'CONFIG_OMAP_IOMMU', 'CONFIG_RTC_HCTOSYS'):
        assert new.get(key) != 'y', key
    assert new['CONFIG_SMP'] == 'y' and new['CONFIG_NR_CPUS'] == '2'
    assert new['CONFIG_HOTPLUG_CPU'] == 'y'
    assert new['CONFIG_CMDLINE'] == old['CONFIG_CMDLINE'][:-len(' nosmp"')] + ' maxcpus=1"'
    for key in ('CONFIG_OMAP_WATCHDOG', 'CONFIG_WATCHDOG_NOWAYOUT',
                'CONFIG_TOUCHSCREEN_CYTTSP4'):
        assert new[key] == 'y', key

    before = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after = json.loads((IMAGE / 'rootfs-manifest.json').read_text())
    changed = {'etc/init.d/rcS'}
    assert {name for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)} == changed
    startup = (BASE / 'rootfs/etc/init.d/rcS').read_text()
    assert startup.count('ram108') == 2
    startup = startup.replace('ram108', 'ram109')
    assert (IMAGE / 'rootfs/etc/init.d/rcS').read_text() == startup
    script = HERE / 'network/dhcp-apply-route-dns.sh'
    assert (IMAGE / 'rootfs/usr/sbin/perrier-dhcp-apply-route-dns').read_bytes() == script.read_bytes()
    assert stat.S_IMODE((IMAGE / 'rootfs/usr/sbin/perrier-dhcp-apply-route-dns').stat().st_mode) == 0o755
    assert 'ifconfig eth0 10.77.10.11 netmask 255.255.255.0 up' in startup
    assert '-p 0.0.0.0:22' in startup
    assert '/bin/udhcpc -f -i eth0 -t 3 -T 2' in startup
    assert '10.77.10.11/24' in script.read_text()
    for name, item in after.items():
        path = IMAGE / 'rootfs' / name
        if 'symlink' in item:
            assert path.is_symlink() and str(path.readlink()) == item['symlink'], name
        else:
            assert sha(path) == item['sha256'] and path.stat().st_size == item['bytes'], name
    for name in ('etc/shadow', 'etc/dropbear/ram_host_key',
                 'root/.ssh/authorized_keys'):
        assert stat.S_IMODE((IMAGE / 'rootfs' / name).stat().st_mode) == 0o600
    audit_archive(IMAGE / 'initramfs.cpio', after)
    packed = (IMAGE / 'kernel-build/usr/initramfs_inc_data').read_bytes()
    assert gzip.decompress(packed) == (IMAGE / 'initramfs.cpio').read_bytes()
    assert packed in (IMAGE / 'kernel-build/vmlinux').read_bytes()
    symbols = (IMAGE / 'kernel-build/System.map').read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(' _end'))
    span = image_end - 0xc0000000
    assert span < 0x02000000
    review = dict(manifest, passed=True, kernel_span_bytes=span,
                  changed_rootfs=sorted(changed), smp_config_delta=changes,
                  board_dtb_only_cpu1_status_changed=True, watchdog_proof_preserved=True,
                  separate_static_rescue_address=True, smp_boot_maxcpus_one_hotplug=True,
                  emmc_ram_policy_inherited_from_ram107=True)
    (IMAGE / 'reviewed-image.json').write_text(json.dumps(review, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': manifest['kernel'],
                      'changed_rootfs': sorted(changed),
                      'config_delta_entries': len(changes), 'kernel_span_bytes': span}, indent=2))


if __name__ == '__main__':
    main()
