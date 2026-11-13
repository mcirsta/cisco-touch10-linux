#!/usr/bin/env python3
"""Verify the RAM image's provenance, boot bounds and unchanged board setup."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NATIVE = ROOT/'development/perrier-native'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def config(p):
    return dict(line.split('=', 1) for line in p.read_text().splitlines()
                if line.startswith('CONFIG_') and '=' in line)

def main():
    manifest = json.loads((HERE/'manifest.json').read_text())
    for info in manifest['artifacts'].values():
        p = Path(info['path'])
        assert sha(p) == info['sha256'] and p.stat().st_size == info['size'], p
    assert manifest['artifacts']['board.dtb']['sha256'] == '73444e693857d02d5fc134697349a83e22662572f1dc17725e2878f4b90253a0'
    assert manifest['artifacts']['kexec']['sha256'] == '29885039c61ae9c938bbe133ff5a099deb8f83738cfe632987ac392d0f09b6f6'
    for name, p in [('rootfs_manifest', HERE/'rootfs-manifest.json'),
                    ('initramfs', HERE/'initramfs.cpio'),
                    ('kernel_config', HERE/'kernel-build/.config'),
                    ('patch_manifest', NATIVE/'kernel-patches/manifest.json')]:
        assert manifest[name+'_sha256'] == sha(p), name
    patches = json.loads((NATIVE/'kernel-patches/manifest.json').read_text())['patches']
    for entry in patches:
        assert sha(NATIVE/'kernel-patches'/entry['patch']) == entry['patch_sha256']
        assert sha(ROOT/'development/sources/linux-6.18.48'/entry['path']) == entry['patched_sha256']
    cfg = config(HERE/'kernel-build/.config')
    baseline = config(NATIVE/'baselines/ram43-before-interactive/resolved.config')
    # Keep all previously reviewed electrical and hardware-driver choices.
    for key in set(cfg) | set(baseline):
        if key.startswith(('CONFIG_ARCH_', 'CONFIG_MACH_', 'CONFIG_GPIO_', 'CONFIG_PINCTRL',
                           'CONFIG_REGULATOR', 'CONFIG_CLK_', 'CONFIG_TWL', 'CONFIG_MFD_',
                           'CONFIG_DRM_', 'CONFIG_OMAP', 'CONFIG_MMC_', 'CONFIG_USB_',
                           'CONFIG_I2C_', 'CONFIG_CPU_', 'CONFIG_PM_', 'CONFIG_POWER_',
                           'CONFIG_SOUND', 'CONFIG_WATCHDOG', 'CONFIG_SUSPEND', 'CONFIG_SMP')):
            assert cfg.get(key) == baseline.get(key), key
    for key in ('BINFMT_SCRIPT','UNIX98_PTYS','UNIX','INET','EPOLL','EVENTFD',
                'SIGNALFD','TIMERFD','PROC_SYSCTL','SYSCTL','SYSVIPC','COREDUMP',
                'INOTIFY_USER','FHANDLE','FILE_LOCKING','DEVMEM','DEBUG_FS','INPUT_EVDEV','INPUT_UINPUT'):
        assert cfg.get('CONFIG_'+key) == 'y', key
    for key in ('WATCHDOG','SMP','CPU_IDLE','CPU_FREQ','SUSPEND','PINCTRL_SINGLE','MODULES'):
        assert cfg.get('CONFIG_'+key) != 'y', key
    assert cfg['CONFIG_LOCALVERSION'] == '"-perrier-ram44"'
    assert cfg['CONFIG_INITRAMFS_SOURCE'] == '"'+str(HERE/'initramfs.cpio')+'"'
    image_end = next(int(line.split()[0],16) for line in
                     (HERE/'kernel-build/System.map').read_text().splitlines()
                     if line.endswith(' _end'))
    assert image_end - 0xc0000000 < 0x02000000
    fs = HERE/'rootfs'
    entries = json.loads((HERE/'rootfs-manifest.json').read_text())
    for name, info in entries.items():
        p = fs/name
        if 'symlink' in info:
            assert p.is_symlink() and str(p.readlink()) == info['symlink'], name
        else:
            assert sha(p) == info['sha256'] and p.stat().st_size == info['bytes'], name
    for name in ('etc/shadow','etc/dropbear/ram_host_key','root/.ssh/authorized_keys'):
        assert stat.S_IMODE((fs/name).stat().st_mode) == 0o600
    assert stat.S_IMODE((fs/'root/.ssh').stat().st_mode) == 0o700
    assert (fs/'root/.ssh/authorized_keys').read_bytes() == (ROOT/'access/touch10_root_ecdsa.pub').read_bytes()
    assert manifest['guard_sha256'] == sha(fs/'usr/sbin/ram-guard')
    for name in ('etc/init.d/rcS','usr/bin/qt-run'):
        subprocess.run(['sh','-n',str(fs/name)],check=True)
    # Check the packed archive against the staged rootfs, including symlinks.
    data = (HERE/'initramfs.cpio').read_bytes()
    pos = 0
    packed = set()
    while True:
        assert data[pos:pos+6] == b'070701'
        fields = [int(data[pos+6+i*8:pos+14+i*8],16) for i in range(13)]
        mode,size,namesize = fields[1],fields[6],fields[11]
        name = data[pos+110:pos+110+namesize-1].decode()
        start = (pos+110+namesize+3)&~3
        payload = data[start:start+size]
        pos = (start+size+3)&~3
        if name == 'TRAILER!!!': break
        if stat.S_ISREG(mode):
            assert hashlib.sha256(payload).hexdigest() == entries[name]['sha256'], name
            packed.add(name)
        elif stat.S_ISLNK(mode):
            assert payload.decode() == entries[name]['symlink'], name
            packed.add(name)
    assert packed == set(entries)
    changes = {key: {'before':baseline.get(key,'n'),'after':cfg.get(key,'n')}
               for key in sorted(set(cfg)|set(baseline)) if cfg.get(key)!=baseline.get(key)}
    report = dict(manifest,passed=True,kernel_span_bytes=image_end-0xc0000000,
                  config_changes=changes,
                  purpose='Interactive RAM Linux; key-only SSH; unchanged board DTB; inherited WDT2 reloads with bounded host lease')
    (HERE/'reviewed-image.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'kernel':manifest['kernel'],
                      'kernel_span_bytes':report['kernel_span_bytes'],
                      'config_changes':changes},indent=2))

if __name__ == '__main__': main()
