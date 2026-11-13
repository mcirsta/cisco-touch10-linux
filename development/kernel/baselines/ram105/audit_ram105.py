#!/usr/bin/env python3
"""Audit the RAM IPv6/DHCP trial against qualified ram104."""
import gzip
import json
from pathlib import Path
import stat

from common import ROOT, HERE, SOURCE, WORK, audit_archive, sha

IMAGE = ROOT / 'development/perrier-ramenv/network-dualstack'
BASE = ROOT / 'development/perrier-ramenv/mailbox-audio-dt'


def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def main():
    manifest = json.loads((IMAGE / 'manifest.json').read_text())
    base = json.loads((BASE / 'reviewed-image.json').read_text())
    assert base['passed'] and base['kernel'] == '6.18.48-perrier-ram104'
    assert manifest['kernel'] == '6.18.48-perrier-ram105'
    assert manifest['profile'] == 'network-dualstack'
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
    assert sha(IMAGE / 'board.dtb') == sha(BASE / 'board.dtb')
    assert sha(HERE / 'patches/manifest.json') == \
        sha(HERE / 'baselines/ram104/patches/manifest.json')
    patches = json.loads((HERE / 'patches/manifest.json').read_text())
    for name, item in patches['files'].items():
        assert sha(SOURCE / name) == sha(WORK / name) == item['after_sha256'], name
    for name in ('drivers/net/ipv6/addrconf.c', 'net/ipv6/addrconf.c',
                 'drivers/net/usb/smsc95xx.c'):
        assert name not in patches['files'], name

    old = config(BASE / 'kernel-build/.config')
    new = config(IMAGE / 'kernel-build/.config')
    changes = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    ipv6 = {'CONFIG_IPV6', 'CONFIG_CRYPTO_LIB_SHA1',
            'CONFIG_CRYPTO_LIB_SHA1_ARCH', 'CONFIG_DST_CACHE',
            'CONFIG_GRO_CELLS', 'CONFIG_INET_TUNNEL',
            'CONFIG_IPV6_NDISC_NODETYPE', 'CONFIG_IPV6_SIT',
            'CONFIG_NET_IP_TUNNEL'}
    assert changes == ipv6 | {'CONFIG_LOCALVERSION',
                              'CONFIG_INITRAMFS_SOURCE'}, changes
    assert new['CONFIG_IPV6'] == 'y'
    assert new['CONFIG_LOCALVERSION'] == '"-perrier-ram105"'
    assert new['CONFIG_INITRAMFS_SOURCE'] == '"' + str(IMAGE / 'initramfs.cpio') + '"'
    for key in ('CONFIG_CPU_FREQ', 'CONFIG_REGULATOR_TWL4030',
                'CONFIG_REGULATOR_TWL6030', 'CONFIG_REMOTEPROC',
                'CONFIG_OMAP_IOMMU', 'CONFIG_RTC_HCTOSYS', 'CONFIG_SMP'):
        assert new.get(key) != 'y', key
    for key in ('CONFIG_OMAP_WATCHDOG', 'CONFIG_WATCHDOG_NOWAYOUT',
                'CONFIG_TOUCHSCREEN_CYTTSP4'):
        assert new[key] == 'y', key

    before = json.loads((BASE / 'rootfs-manifest.json').read_text())
    after = json.loads((IMAGE / 'rootfs-manifest.json').read_text())
    changed = {'etc/init.d/rcS', 'usr/sbin/perrier-dhcp-observe'}
    assert {name for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)} == changed
    startup = (BASE / 'rootfs/etc/init.d/rcS').read_text().replace('ram104', 'ram105')
    marker = 'echo $! > /run/ssh.pid\n'
    dhcp = ('( /bin/udhcpc -i eth0 -n -q -t 3 -T 2 '
            '-s /usr/sbin/perrier-dhcp-observe > /run/dhcp.log 2>&1; '
            'echo $? > /run/dhcp-exit ) &\n')
    assert startup.count(marker) == 1
    assert (IMAGE / 'rootfs/etc/init.d/rcS').read_text() == \
        startup.replace(marker, marker + dhcp)
    script = HERE / 'network/dhcp-observe.sh'
    assert (IMAGE / 'rootfs/usr/sbin/perrier-dhcp-observe').read_bytes() == script.read_bytes()
    assert stat.S_IMODE((IMAGE / 'rootfs/usr/sbin/perrier-dhcp-observe').stat().st_mode) == 0o755
    assert 'ifconfig eth0 10.77.10.10 netmask 255.255.255.0 up' in startup
    assert 'ifconfig' not in script.read_text() and 'ip addr' not in script.read_text()
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
                  changed_rootfs=sorted(changed), new_mainline_config=sorted(ipv6),
                  board_dtb_identical_to_ram104=True, watchdog_proof_preserved=True,
                  static_ram_ssh_address_preserved=True, dhcp_observation_only=True,
                  emmc_ram_policy_inherited_from_ram104=True)
    (IMAGE / 'reviewed-image.json').write_text(json.dumps(review, indent=2) + '\n')
    print(json.dumps({'passed': True, 'kernel': manifest['kernel'],
                      'changed_rootfs': sorted(changed),
                      'new_config': sorted(ipv6), 'kernel_span_bytes': span}, indent=2))


if __name__ == '__main__':
    main()
