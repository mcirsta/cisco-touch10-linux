#!/usr/bin/env python3
"""Build ram111 with a read-only TWL6032 SMPS1 voltage observation path."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import libfdt

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RAM = ROOT / 'development/perrier-ramenv'
BASE = RAM / 'smp-boot-two'
DEST = RAM / 'smps1-observe'
FS = DEST / 'rootfs'
OUT = DEST / 'kernel-build'
SRC = HERE / 'work/linux-6.18.48'
from common import SOURCE, cpio_entry, audit_archive


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    raise RuntimeError('ram111 was invalidated: CTL-I2C does not expose the live SmartReflex selector')
    os.umask(0o077)
    run(['python3', HERE / 'export_patches.py'])
    run(['python3', HERE / 'prepare_source.py'])
    baseline_path = BASE / 'reviewed-image.json'
    baseline = json.loads(baseline_path.read_text())
    proof_path = RAM / 'native-watchdog/watchdog-proof.json'
    proof = json.loads(proof_path.read_text())
    assert baseline['passed'] and baseline['kernel'] == '6.18.48-perrier-ram110'
    assert proof['status'] == 'passed' and proof['guard_sha256'] == baseline['guard_sha256']
    for item in baseline['artifacts'].values():
        assert sha(Path(item['path'])) == item['sha256']
    assert sha(BASE / 'rootfs-manifest.json') == baseline['rootfs_manifest_sha256']
    assert sha(BASE / 'kernel-build/.config') == baseline['kernel_config_sha256']
    entries = json.loads((BASE / 'rootfs-manifest.json').read_text())
    for name, item in entries.items():
        path = BASE / 'rootfs' / name
        if 'symlink' in item:
            assert path.is_symlink() and str(path.readlink()) == item['symlink'], name
        else:
            assert sha(path) == item['sha256'], name
    DEST.mkdir(exist_ok=True)
    if FS.exists():
        shutil.rmtree(FS)
    shutil.copytree(BASE / 'rootfs', FS, symlinks=True)
    startup = (FS / 'etc/init.d/rcS').read_text()
    assert startup.count('ram110') == 2
    startup = startup.replace('ram110', 'ram111')
    (FS / 'etc/init.d/rcS').write_text(startup)
    qt = ROOT / 'development/perrier-qt'
    audio = ROOT / 'development/audio'
    script = HERE / 'network/dhcp-apply-route-dns.sh'
    changed = {'etc/init.d/rcS'}
    root_manifest, chunks = {}, []
    for path in sorted(FS.rglob('*')):
        name = str(path.relative_to(FS))
        if path.is_symlink():
            target = str(path.readlink())
            chunks.append(cpio_entry(name, stat.S_IFLNK | 0o777, target.encode()))
            root_manifest[name] = {'symlink': target}
        elif path.is_dir():
            chunks.append(cpio_entry(name, stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode)))
        else:
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            assert payload == path.read_bytes(), 'Unstable payload read: ' + name
            if name not in changed:
                assert digest == entries[name]['sha256'], name
            chunks.append(cpio_entry(name, stat.S_IFREG | stat.S_IMODE(path.stat().st_mode), payload))
            root_manifest[name] = {'sha256': digest, 'bytes': len(payload)}
    chunks.append(cpio_entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1))
    chunks.append(cpio_entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3))
    chunks.append(cpio_entry('TRAILER!!!', 0))
    temporary = DEST / 'initramfs.cpio.new'
    expected_archive = hashlib.sha256()
    with temporary.open('wb') as stream:
        for chunk in chunks:
            expected_archive.update(chunk)
            assert stream.write(chunk) == len(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    assert sha(temporary) == expected_archive.hexdigest(), 'Archive differs after writing'
    audit_archive(temporary, root_manifest)
    temporary.replace(DEST / 'initramfs.cpio')
    (DEST / 'rootfs-manifest.json').write_text(json.dumps(root_manifest, indent=2) + '\n')
    archive_digest = sha(DEST / 'initramfs.cpio')
    audit_archive(DEST / 'initramfs.cpio', root_manifest)
    print('Verified packed archive before compilation: ' + archive_digest, flush=True)
    OUT.mkdir(exist_ok=True)
    shutil.copy2(HERE / 'configs/perrier-ram111.config', OUT / '.config')
    original_cmdline = next(line.split('=', 1)[1].strip('"') for line in
                            (BASE / 'kernel-build/.config').read_text().splitlines()
                            if line.startswith('CONFIG_CMDLINE='))
    assert ' maxcpus=1' not in original_cmdline
    run([SRC / 'scripts/config', '--file', OUT / '.config',
         '--set-str', 'LOCALVERSION', '-perrier-ram111',
         '--set-str', 'INITRAMFS_SOURCE', DEST / 'initramfs.cpio',
         '--set-str', 'CMDLINE', original_cmdline,
         '--enable', 'SMP', '--set-val', 'NR_CPUS', '2',
         '--enable', 'HOTPLUG_CPU', '--enable', 'REGULATOR_TWL4030'])
    make = ['make', '-C', SRC, f'O={OUT}', 'ARCH=arm', 'LLVM=1']
    env = dict(os.environ, KBUILD_BUILD_USER='touch10', KBUILD_BUILD_HOST='perrier-dev',
               KBUILD_BUILD_TIMESTAMP='2026-11-12 00:00:00 UTC')
    run(make + ['olddefconfig'], env=env)
    final_config = (OUT / '.config').read_text()
    assert 'CONFIG_REGULATOR_TWL4030=y' in final_config
    assert '# CONFIG_CPU_FREQ is not set' in final_config
    assert 'CONFIG_WATCHDOG_NOWAYOUT=y' in final_config
    assert 'CONFIG_SMP=y' in final_config
    assert 'CONFIG_NR_CPUS=2' in final_config
    assert 'CONFIG_HOTPLUG_CPU=y' in final_config
    shutil.copy2(OUT / '.config', DEST / 'kernel.config')
    run(make + ['-j' + str(os.cpu_count() or 1), 'zImage'], env=env)
    assert sha(DEST / 'initramfs.cpio') == archive_digest, 'Archive changed during compilation'
    run(make + ['ti/omap/omap4-cisco-perrier-mailbox-ram.dtb'], env=env)
    compiled_dtb = OUT / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-mailbox-ram.dtb'
    fdt = libfdt.Fdt(compiled_dtb.read_bytes())
    fdt.resize(fdt.totalsize() + 1024)
    fdt.setprop(fdt.path_offset('/cpus/cpu@1'), 'status', b'okay\0')
    fdt.pack()
    (DEST / 'board.dtb').write_bytes(bytes(fdt.as_bytearray()[:fdt.totalsize()]))
    dtc = OUT / 'scripts/dtc/dtc'
    base_dt = subprocess.run([dtc, '-I', 'dtb', '-O', 'dts', '-q', BASE / 'board.dtb'],
                             check=True, capture_output=True, text=True).stdout
    trial_dt = subprocess.run([dtc, '-I', 'dtb', '-O', 'dts', '-q', DEST / 'board.dtb'],
                              check=True, capture_output=True, text=True).stdout
    trial_dt, count = re.subn(r'\n\s*regulator-smps1 \{\n[^{}]*\n\s*\};', '', trial_dt,
                              count=1)
    assert count == 1 and trial_dt == base_dt, 'Unexpected DTB change'
    files = {'zImage': OUT / 'arch/arm/boot/zImage', 'board.dtb': DEST / 'board.dtb',
             'kexec': ROOT / 'development/perrier/kexec-legacy-fdt'}
    inputs = {'baseline_review': baseline_path, 'watchdog_proof': proof_path,
              'confirmed_baseline': HERE / 'validation-ram110-extended.json',
              'qt_app_source': qt / 'app/main.cpp',
              'qt_ui_source': qt / 'app/Main.qml',
              'qt_audio_source': qt / 'app/audio_backend.cpp',
              'qt_audio_header': qt / 'app/audio_backend.h',
              'qt_pcm_setup': qt / 'app/pcm_setup.h',
              'alsa_config': audio / 'asound-mix.conf',
              'alsa_library': audio / 'shared-install/libasound-dmix.so.2',
              'alsa_build_script': audio / 'build_dmix_lib.py',
              'alsa_build_record': HERE / 'out/application-audio/dmix-build.json',
              'alsa_live_record': audio / 'shared-playback.md',
              'qt_runtime_manifest': qt / 'runtime-manifest.json',
              'dhcp_apply_script': script,
              'dhcp_script_test': HERE / 'network/test_dhcp_apply.py',
              'test_lan_policy': HERE / 'network/isolated-dhcp-policy.json',
              'source_manifest': HERE / 'patches/manifest.json',
              'ram_config': HERE / 'configs/perrier-ram111.config',
              'boot_two_config_delta': HERE / 'configs/cpu1-boot-two-config-delta.json',
              'bus_policy': HERE / 'configs/bus-layout.json',
              'diagnostics_policy': HERE / 'configs/diagnostics-layout.json',
              'hardware_dtsi': SOURCE / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier.dtsi',
              'ram_dts': SOURCE / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dts',
              'mailbox_ram_dts': SOURCE / 'arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-mailbox-ram.dts'}
    manifest = {'kernel': '6.18.48-perrier-ram111', 'profile': 'smps1-observe',
                'artifacts': {name: {'path': str(path), 'size': path.stat().st_size, 'sha256': sha(path)}
                              for name, path in files.items()},
                'inputs': {name: {'path': str(path), 'sha256': sha(path)} for name, path in inputs.items()},
                'rootfs_manifest_sha256': sha(DEST / 'rootfs-manifest.json'),
                'initramfs_sha256': sha(DEST / 'initramfs.cpio'),
                'kernel_config_sha256': sha(OUT / '.config'),
                'guard_sha256': sha(FS / 'usr/sbin/ram-guard'),
                'watchdog_backend': 'linux-watchdog'}
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
