#!/usr/bin/env python3
"""Assemble ram116 from freshly built userspace, without a prior RAM image."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
TOOLCHAIN = "armv7-eabihf--musl--stable-2026.08-1"
COMPILER_PREFIX = "arm-buildroot-linux-musleabihf-"
PROFILE = "cpu-dvfs-mid-trial"
KERNEL_RELEASE = "6.18.48-perrier-ram116"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_key(path: Path) -> str:
    """Accept OpenSSH public keys, never a private key or SSH options."""
    text = path.read_text()
    if "PRIVATE KEY" in text:
        raise ValueError("--authorized-key requires an OpenSSH public key")
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        raise ValueError("authorized key file is empty")
    for line in lines:
        parts = line.split()
        if len(parts) < 2 or parts[0] not in {
            "ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
        }:
            raise ValueError("expected an OpenSSH public-key line without options")
        try:
            decoded = base64.b64decode(parts[1], validate=True)
        except ValueError as error:
            raise ValueError("invalid public-key base64") from error
        if len(decoded) < 4:
            raise ValueError("truncated public key")
        length = struct.unpack(">I", decoded[:4])[0]
        if decoded[4:4 + length] != parts[0].encode():
            raise ValueError("public-key type does not match its payload")
    return "\n".join(lines) + "\n"


def cpio_entry(name: str, mode: int, data: bytes = b"", major: int = 0, minor: int = 0) -> bytes:
    encoded = name.encode() + b"\0"
    fields = (1, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(encoded), 0)
    header = b"070701" + b"".join(f"{value:08x}".encode() for value in fields) + encoded
    return header + bytes(-len(header) % 4) + data + bytes(-len(data) % 4)


def pack_rootfs(rootfs: Path, archive: Path) -> dict:
    """Write deterministic newc headers, root ownership and explicit devices."""
    entries = {}
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + ".new")
    with temporary.open("wb") as stream:
        for path in sorted(rootfs.rglob("*")):
            name = path.relative_to(rootfs).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = str(path.readlink())
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                if target.startswith("/") or resolved == ".." or resolved.startswith("../"):
                    raise ValueError("rootfs link escapes the image: " + name)
                stream.write(cpio_entry(name, stat.S_IFLNK | 0o777, target.encode()))
                entries[name] = {"symlink": target}
            elif stat.S_ISDIR(mode):
                stream.write(cpio_entry(name, stat.S_IFDIR | stat.S_IMODE(mode)))
            elif stat.S_ISREG(mode):
                data = path.read_bytes()
                stream.write(cpio_entry(name, stat.S_IFREG | stat.S_IMODE(mode), data))
                entries[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            else:
                raise ValueError("unexpected rootfs file type: " + name)
        stream.write(cpio_entry("dev/console", stat.S_IFCHR | 0o600, major=5, minor=1))
        stream.write(cpio_entry("dev/null", stat.S_IFCHR | 0o666, major=1, minor=3))
        stream.write(cpio_entry("TRAILER!!!", 0))
        stream.flush()
        os.fsync(stream.fileno())
    audit_archive(temporary, entries)
    temporary.replace(archive)
    return entries


def audit_archive(path: Path, entries: dict) -> None:
    """Independently parse the packed archive and verify every payload."""
    data = path.read_bytes()
    position, seen, payloads = 0, set(), set()
    while True:
        if data[position:position + 6] != b"070701":
            raise ValueError("invalid newc header")
        fields = [int(data[position + 6 + index * 8:position + 14 + index * 8], 16)
                  for index in range(13)]
        mode, uid, gid, mtime, size, namesize = fields[1], fields[2], fields[3], fields[5], fields[6], fields[11]
        assert uid == gid == mtime == 0
        name = data[position + 110:position + 110 + namesize - 1].decode()
        assert name not in seen
        seen.add(name)
        start = (position + 110 + namesize + 3) & ~3
        content = data[start:start + size]
        assert len(content) == size
        position = (start + size + 3) & ~3
        if name == "TRAILER!!!":
            break
        if stat.S_ISREG(mode):
            assert hashlib.sha256(content).hexdigest() == entries[name]["sha256"], name
            assert len(content) == entries[name]["bytes"], name
            payloads.add(name)
        elif stat.S_ISLNK(mode):
            assert content.decode() == entries[name]["symlink"], name
            payloads.add(name)
        elif stat.S_ISCHR(mode):
            assert (name, fields[9], fields[10]) in {("dev/console", 5, 1), ("dev/null", 1, 3)}
        else:
            assert stat.S_ISDIR(mode), name
    assert payloads == set(entries) and position == len(data)


def audit_rootfs(rootfs: Path, *, ssh_enabled: bool) -> dict:
    required = ("bin/busybox", "usr/sbin/ram-guard", "usr/bin/event-dump", "usr/bin/aplay",
                "usr/sbin/dropbear", "usr/sbin/dropbearkey", "usr/bin/scp", "usr/bin/strace",
                "usr/sbin/perrier-dhcp-apply-route-dns", "qt/bin/perrier-touch-grid",
                "qt/lib/libasound.so.2", "etc/asound.conf", "etc/init.d/rcS", "usr/bin/qt-run")
    for name in required:
        assert (rootfs / name).is_file(), "missing rootfs input: " + name
    assert (rootfs / "init").readlink() == PurePosixPath("bin/busybox")
    assert (rootfs / "lib").readlink() == PurePosixPath("qt/lib")
    assert (rootfs / "etc/shadow").read_text() == "root:*:0:0:99999:7:::\n"
    startup = (rootfs / "etc/init.d/rcS").read_text()
    assert "/usr/sbin/ram-guard daemon" in startup
    assert "PERRIER_GUARD_START_FAILED" in startup
    assert "/usr/sbin/perrier-dhcp-apply-route-dns" in startup
    # The early image mounts pseudo-filesystems only; eMMC is never mounted.
    for line in startup.splitlines():
        if line.startswith("mount "):
            assert line.split()[2] in {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "debugfs"}, line
    host_key = rootfs / "etc/dropbear/ram_host_key"
    authorized = rootfs / "root/.ssh/authorized_keys"
    assert host_key.exists() == ssh_enabled
    assert authorized.exists() == ssh_enabled
    assert (rootfs / "etc/dropbear/ssh-enabled").exists() == ssh_enabled
    if ssh_enabled:
        assert stat.S_IMODE(host_key.stat().st_mode) == 0o600
        assert stat.S_IMODE(authorized.stat().st_mode) == 0o600
    elf_count = 0
    for path in rootfs.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                header = stream.read(20)
            if header.startswith(b"\x7fELF"):
                assert header[4:6] == b"\x01\x01" and struct.unpack_from("<H", header, 18)[0] == 40, path
                elf_count += 1
    return {"passed": True, "arm_elf_files": elf_count, "ssh_enabled": ssh_enabled,
            "watchdog_backend": "linux-watchdog", "emmc_filesystems_mounted": False}


def build_rootfs(project_root: Path, destination: Path, *, authorized_key: Path | None = None) -> dict:
    project_root, destination = project_root.resolve(), destination.resolve()
    legacy = project_root / "development/perrier-ramenv"
    if destination == project_root or destination == legacy or destination.is_relative_to(legacy):
        raise ValueError("standalone output must not overwrite a historical image")
    key_text = public_key(authorized_key) if authorized_key is not None else None
    tc = project_root / "development/perrier-qt/sources" / TOOLCHAIN
    prefix = tc / "bin" / COMPILER_PREFIX
    gcc, strip = Path(str(prefix) + "gcc"), Path(str(prefix) + "strip")
    ram = project_root / "development/perrier-ramenv"
    qt = project_root / "development/perrier-qt/runtime"
    audio = project_root / "development/audio"
    tools = {
        "bin/busybox": ram / "sources/busybox-1.37.0/busybox",
        "usr/sbin/dropbear": ram / "sources/dropbear-2026.94/dropbear",
        "usr/sbin/dropbearkey": ram / "sources/dropbear-2026.94/dropbearkey",
        "usr/bin/scp": ram / "sources/dropbear-2026.94/scp",
        "usr/bin/strace": ram / "sources/strace-7.3/src/strace",
        "usr/bin/gdbserver": tc / "arm-buildroot-linux-musleabihf/debug-root/usr/bin/gdbserver",
        "usr/bin/aplay": audio / "app-build/alsa-utils/aplay/aplay",
    }
    for path in (*tools.values(), gcc, strip, qt / "bin/perrier-touch-grid",
                 audio / "shared-install/libasound-dmix.so.2"):
        if not path.is_file():
            raise FileNotFoundError("build userspace before assembling rootfs: " + str(path))
    destination.mkdir(parents=True, exist_ok=True)
    rootfs = destination / "rootfs"
    if rootfs.is_symlink():
        raise ValueError("rootfs output may not be a symlink")
    if rootfs.exists():
        shutil.rmtree(rootfs)
    rootfs.mkdir(mode=0o700)
    for name in ("dev", "proc", "sys", "run", "tmp", "root/.ssh", "etc/dropbear", "bin", "sbin", "usr/bin", "usr/sbin"):
        (rootfs / name).mkdir(parents=True, exist_ok=True)
    for name in ("root", "root/.ssh", "etc/dropbear"):
        (rootfs / name).chmod(0o700)
    (rootfs / "tmp").chmod(0o1777)
    inputs = {}

    def copy(source: Path, name: str, mode: int | None = None, *, stripped: bool = False) -> None:
        target = rootfs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if mode is not None:
            target.chmod(mode)
        if stripped:
            subprocess.run([str(strip), "--strip-unneeded", str(target)], check=True)
        if source.is_relative_to(project_root):
            label = source.relative_to(project_root).as_posix()
        elif source.is_relative_to(destination):
            label = "output/" + source.relative_to(destination).as_posix()
        elif source.is_relative_to(HERE):
            label = "development/standalone/" + source.relative_to(HERE).as_posix()
        else:
            raise ValueError("unexpected rootfs input outside the source and output trees")
        inputs[label] = sha(source)

    def put(name: str, text: str, mode: int = 0o644) -> None:
        target = rootfs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        target.chmod(mode)

    for name, source in tools.items():
        copy(source, name, 0o755, stripped=True)
    listing = subprocess.run(["qemu-arm", "-cpu", "cortex-a9", str(tools["bin/busybox"]), "--list"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    assert "sh" in listing and "init" in listing
    for name in listing:
        if name != "busybox":
            assert "/" not in name and name not in {".", ".."}
            (rootfs / "bin" / name).symlink_to("busybox")
    (rootfs / "init").symlink_to("bin/busybox")
    (rootfs / "sbin/init").symlink_to("../bin/busybox")
    shutil.copytree(qt, rootfs / "qt", symlinks=True)
    for source in qt.rglob("*"):
        if source.is_file() and not source.is_symlink():
            inputs[source.relative_to(project_root).as_posix()] = sha(source)
    (rootfs / "lib").symlink_to("qt/lib")
    (rootfs / "usr/lib").symlink_to("../lib")
    shutil.copytree(audio / "app-install/etc/alsa", rootfs / "etc/alsa", symlinks=True)
    copy(audio / "asound-mix.conf", "etc/asound.conf", 0o644)
    copy(audio / "shared-install/libasound-dmix.so.2", "qt/lib/libasound.so.2", 0o755)
    copy(audio / "alsa-utils/COPYING", "usr/share/licenses/alsa-utils.txt", 0o644)
    copy(project_root / "development/kernel/network/dhcp-apply-route-dns.sh",
         "usr/sbin/perrier-dhcp-apply-route-dns", 0o755)
    copy(project_root / "development/perrier-ramenv/qt-run", "usr/bin/qt-run", 0o755)
    copy(project_root / "development/standalone/templates/rcS", "etc/init.d/rcS", 0o755)
    put("etc/passwd", "root:x:0:0:root:/root:/bin/sh\n")
    put("etc/group", "root:x:0:\n")
    put("etc/shadow", "root:*:0:0:99999:7:::\n", 0o600)
    put("etc/shells", "/bin/sh\n/bin/ash\n")
    put("etc/hosts", "127.0.0.1 localhost\n10.77.10.10 touch10-ram\n10.77.10.1 host\n")
    put("etc/profile", 'export PATH=/bin:/sbin:/usr/bin:/usr/sbin\nexport PS1="touch10-ram# "\ncd /tmp\n')
    put("etc/inittab", "::sysinit:/etc/init.d/rcS\nttyS0::respawn:-/bin/sh\n::ctrlaltdel:/bin/reboot\n::shutdown:/bin/sync\n")
    helpers = {
        "usr/sbin/ram-guard": project_root / "development/perrier-watchdog/ram_guard_device.c",
        "usr/bin/event-dump": project_root / "development/perrier-ramenv/event_dump.c",
    }
    helper_dir = destination / "helpers"
    helper_dir.mkdir(exist_ok=True)
    for name, source in helpers.items():
        target = helper_dir / Path(name).name
        subprocess.run([str(gcc), "-O2", "-g", "-Wall", "-Wextra", "-static", "-mcpu=cortex-a9",
                        "-mfpu=neon", "-mfloat-abi=hard", str(source), "-o", str(target)], check=True)
        copy(target, name, 0o755, stripped=True)
        inputs[source.relative_to(project_root).as_posix()] = sha(source)
    if key_text is not None:
        put("root/.ssh/authorized_keys", key_text, 0o600)
        host_key = rootfs / "etc/dropbear/ram_host_key"
        keygen = tools["usr/sbin/dropbearkey"]
        subprocess.run(["qemu-arm", "-cpu", "cortex-a9", str(keygen), "-t", "ecdsa", "-s", "256", "-f", str(host_key)],
                       capture_output=True, check=True)
        host_key.chmod(0o600)
        result = subprocess.run(["qemu-arm", "-cpu", "cortex-a9", str(keygen), "-y", "-f", str(host_key)],
                                capture_output=True, text=True, check=True)
        host_public = next(line for line in result.stdout.splitlines() if line.startswith("ecdsa-sha2-"))
        (destination / "known_hosts").write_text("10.77.10.10 " + host_public + "\n10.77.10.11 " + host_public + "\n")
        put("etc/dropbear/ssh-enabled", "explicit public key supplied at build time\n", 0o600)
    elif (destination / "known_hosts").exists():
        (destination / "known_hosts").unlink()
    audit = audit_rootfs(rootfs, ssh_enabled=key_text is not None)
    entries = pack_rootfs(rootfs, destination / "initramfs.cpio")
    (destination / "rootfs-manifest.json").write_text(json.dumps(entries, indent=2) + "\n")
    record = {"profile": PROFILE, "kernel": KERNEL_RELEASE, "inputs": inputs,
              "rootfs_manifest_sha256": sha(destination / "rootfs-manifest.json"),
              "initramfs_sha256": sha(destination / "initramfs.cpio"),
              "guard_source": "development/perrier-watchdog/ram_guard_device.c",
              "guard_sha256": sha(rootfs / "usr/sbin/ram-guard"),
              "prebuilt_external_runtime": "Fresh Bootlin compiler runtime and its gdbserver; no prior project image inputs.",
              "audit": audit, "live_tested": False}
    (destination / "rootfs-build.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "out/ram116")
    parser.add_argument("--authorized-key", type=Path)
    args = parser.parse_args()
    record = build_rootfs(HERE.parents[1], args.output, authorized_key=args.authorized_key)
    print(json.dumps({"built": True, "profile": PROFILE, "audit": record["audit"]}, indent=2))


if __name__ == "__main__":
    main()
