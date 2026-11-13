#!/usr/bin/env python3
"""Audit ram53: SMP and CPU1 only, relative to the tested ram52 image."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RAM = ROOT/'development/perrier-ramenv'
BASE = RAM/'native-keypad'
DEST = RAM/'native-smp'
HERE = Path(__file__).resolve().parent
fdt_nodes = runpy.run_path(str(ROOT/'development/perrier-simpledrm/audit.py'))['fdt_nodes']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def config(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def audit():
    manifest = json.loads((DEST/'manifest.json').read_text())
    assert manifest['profile'] == 'native-smp'
    assert manifest['kernel'] == '6.18.48-perrier-ram53'
    for info in manifest['artifacts'].values():
        path = Path(info['path'])
        assert sha(path) == info['sha256'] and path.stat().st_size == info['size'], path
    assert sha(DEST/'initramfs.cpio') == manifest['initramfs_sha256']
    assert sha(DEST/'rootfs-manifest.json') == manifest['rootfs_manifest_sha256']
    assert sha(DEST/'kernel-build/.config') == manifest['kernel_config_sha256']
    for source, key in (
        (HERE/'omap4-perrier-smp.dts','smp_dts_sha256'),
        (ROOT/'development/perrier-keypad/omap4-perrier-keypad.dts','keypad_dts_sha256'),
        (ROOT/'development/perrier-backlight/omap4-perrier-backlight.dts','backlight_dts_sha256'),
        (ROOT/'development/perrier-touch/omap4-perrier-touch.dts','touch_dts_sha256'),
        (ROOT/'development/perrier-native/omap4-perrier-ram.dts','base_dts_sha256'),
    ):
        assert sha(source) == manifest[key], source
    assert manifest['guard_sha256'] == sha(DEST/'rootfs/usr/sbin/ram-guard')
    proof = json.loads((RAM/'watchdog-proof.json').read_text())
    assert proof['status'] == 'passed' and proof['guard_sha256'] == manifest['guard_sha256']

    old = fdt_nodes((BASE/'board.dtb').read_bytes())
    new = fdt_nodes((DEST/'board.dtb').read_bytes())
    assert set(old) == set(new)
    cpu = '/cpus/cpu@1'
    assert old[cpu]['status'] == b'disabled\0'
    assert new[cpu]['status'] == b'okay\0'
    for path in old:
        previous = {k:v for k,v in old[path].items() if not (path == cpu and k == 'status')}
        current = {k:v for k,v in new[path].items() if not (path == cpu and k == 'status')}
        assert previous == current, path

    old_cfg = config(BASE/'kernel-build/.config')
    new_cfg = config(DEST/'kernel-build/.config')
    changes = {k:{'before':old_cfg.get(k,'n'),'after':new_cfg.get(k,'n')}
               for k in sorted(set(old_cfg)|set(new_cfg))
               if old_cfg.get(k) != new_cfg.get(k)}
    expected = {
        'CONFIG_ARCH_HAS_TICK_BROADCAST', 'CONFIG_ARCH_NEEDS_CPU_IDLE_COUPLED',
        'CONFIG_ARCH_SUPPORTS_KEXEC', 'CONFIG_BROKEN_ON_SMP',
        'CONFIG_CONTEXT_TRACKING', 'CONFIG_CONTEXT_TRACKING_IDLE',
        'CONFIG_FORCE_NR_CPUS', 'CONFIG_GENERIC_CLOCKEVENTS_BROADCAST',
        'CONFIG_GENERIC_IRQ_EFFECTIVE_AFF_MASK', 'CONFIG_GENERIC_IRQ_IPI',
        'CONFIG_HAVE_ARM_SCU', 'CONFIG_HAVE_ARM_TWD',
        'CONFIG_HAVE_HARDLOCKUP_DETECTOR_BUDDY', 'CONFIG_INITRAMFS_SOURCE',
        'CONFIG_KVFREE_RCU_BATCHED', 'CONFIG_LOCALVERSION',
        'CONFIG_LOCK_SPIN_ON_OWNER', 'CONFIG_LOG_CPU_MAX_BUF_SHIFT',
        'CONFIG_MUTEX_SPIN_ON_OWNER', 'CONFIG_NEED_PER_CPU_KM',
        'CONFIG_NEED_SRCU_NMI_SAFE', 'CONFIG_NR_CPUS', 'CONFIG_PER_VMA_LOCK',
        'CONFIG_RCU_CPU_STALL_TIMEOUT', 'CONFIG_RCU_EXP_CPU_STALL_TIMEOUT',
        'CONFIG_RCU_NEED_SEGCBLIST', 'CONFIG_RCU_STALL_COMMON',
        'CONFIG_RWSEM_SPIN_ON_OWNER', 'CONFIG_SMP',
        'CONFIG_SOCK_RX_QUEUE_MAPPING', 'CONFIG_SWP_EMULATE',
        'CONFIG_TINY_RCU', 'CONFIG_TINY_SRCU', 'CONFIG_TREE_RCU',
        'CONFIG_TREE_SRCU', 'CONFIG_XPS',
    }
    assert set(changes) == expected, set(changes)^expected
    assert new_cfg['CONFIG_SMP'] == 'y'
    assert new_cfg['CONFIG_NR_CPUS'] == '2'
    # Mainline ARM's SMP Kconfig drops in-kernel kexec support; the host still
    # enters this RAM image from stock via the existing kexec loader.
    assert new_cfg.get('CONFIG_ARCH_SUPPORTS_KEXEC') != 'y'
    for key in ('CONFIG_CPU_FREQ','CONFIG_CPU_IDLE','CONFIG_SUSPEND',
                'CONFIG_PINCTRL_SINGLE','CONFIG_WATCHDOG','CONFIG_MODULES'):
        assert new_cfg.get(key) != 'y', key
    assert new_cfg['CONFIG_LOCALVERSION'] == '"-perrier-ram53"'
    assert new_cfg['CONFIG_INITRAMFS_SOURCE'] == '"'+str(DEST/'initramfs.cpio')+'"'
    startup=(DEST/'rootfs/etc/init.d/rcS').read_text()
    assert 'perrier-interactive-ram53' in startup
    assert 'native-cyttsp4' in startup
    subprocess.run(['sh','-n',DEST/'rootfs/etc/init.d/rcS'],check=True)
    image_end=next(int(line.split()[0],16) for line in
                   (DEST/'kernel-build/System.map').read_text().splitlines()
                   if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    report=dict(manifest,passed=True,kernel_span_bytes=image_end-0xc0000000,
                config_changes=changes,purpose='OMAP4460 CPU1 SMP RAM-only trial')
    (DEST/'reviewed-image.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'kernel':report['kernel'],
                      'config_changes':changes},indent=2))

if __name__ == '__main__':
    audit()
