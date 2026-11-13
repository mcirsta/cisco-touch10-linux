#!/usr/bin/env python3
"""Key-only Touch 10 diagnostics, serial logging and bounded RAM recovery tests.

Execution is limited to a hash-pinned UART/stall payload. There is no flash
operation or unrestricted candidate-kernel execution command.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import select
import shlex
import subprocess
import sys
import termios
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
UART = "/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0"
SSH_CONFIG = ROOT / "access/ssh_config"
STOCK_ENV_SHA256 = "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad"
KEXEC_LOADER_SHA256 = "bff8fcd8dfd508fef0b15edac2df950e406bbd4f7021b5c89007a44a0cfdcfcd"
ARM_WATCHDOG_SHA256 = "49adc4446015e2f92159bb1f3443eb3d43ca9c6d7cd09587e3211cc37a1ecf0a"
KEXEC_STALL_SHA256 = "d9ac364c699d89b1656b6835be22955a7f0acc16164058458dcc6acd2cf1fae3"
PERRIER_LOADER_SHA256 = "29885039c61ae9c938bbe133ff5a099deb8f83738cfe632987ac392d0f09b6f6"
SNAPSHOT = r'''
set -eu
printf 'hostname=%s\n' "$(hostname)"
printf 'uid=%s\n' "$(id -u)"
printf 'kernel=%s\n' "$(uname -r)"
printf 'arch=%s\n' "$(uname -m)"
printf 'boot_id=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'uptime=%s\n' "$(cut -d ' ' -f1 /proc/uptime)"
if pidof phoenix >/dev/null; then printf 'factory_app=running\n'; else printf 'factory_app=absent\n'; fi
printf 'kexec_path=%s\n' "$(command -v kexec || true)"
if [ -r /sys/kernel/kexec_loaded ]; then printf 'kexec_loaded=%s\n' "$(cat /sys/kernel/kexec_loaded)"; fi
if [ -c /dev/watchdog ]; then printf 'watchdog=present\n'; else printf 'watchdog=absent\n'; fi
'''
WATCHDOG_RECOVERY = r'''
set -eu
set -- $(pidof watchdog)
[ "$#" -eq 1 ]
pid=$1
[ "$(cat /proc/$pid/comm)" = watchdog ]
found=no
for fd in /proc/$pid/fd/*; do
    if [ "$(readlink "$fd")" = /dev/watchdog ]; then found=yes; fi
done
[ "$found" = yes ]
# A detached fallback resumes the existing feeder if no reset happens.
# It never opens/reconfigures the watchdog and vanishes on a real reboot.
nohup sh -c '
    sleep 90
    [ "$(cat /proc/$1/comm 2>/dev/null)" = watchdog ] || exit 0
    kill -CONT "$1"
' resume-watchdog "$pid" </dev/null >/dev/null 2>&1 &
printf 'resume_guard_pid=%s\n' "$!"
sync
kill -STOP "$pid"
printf 'watchdog_stopped_pid=%s\n' "$pid"
'''


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class SerialCapture:
    """Receive only: never transmits a command, break or modem-line ioctl."""

    def __init__(self, port: str, directory: Path):
        self.port, self.directory = port, directory
        self.stop_event = threading.Event()
        self.error: str | None = None
        self.byte_count = 0

    def __enter__(self):
        self.fd = os.open(self.port, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.previous = termios.tcgetattr(self.fd)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        except BaseException:
            os.close(self.fd)
            raise
        self.thread = threading.Thread(target=self._receive, daemon=True)
        self.thread.start()
        return self

    def _receive(self):
        pending = b""
        try:
            with (self.directory / "serial.raw").open("wb") as raw, (self.directory / "serial.log").open("w") as log:
                while not self.stop_event.is_set():
                    readable, _, _ = select.select([self.fd], [], [], 0.2)
                    if not readable:
                        continue
                    data = os.read(self.fd, 65536)
                    if not data:
                        raise OSError("UART disconnected or returned EOF")
                    self.byte_count += len(data)
                    raw.write(data)
                    raw.flush()
                    pending += data
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        log.write(f"{now()} {line.decode('utf-8', 'replace').rstrip(chr(13))}\n")
                    # Bound a malformed/no-newline stream as well as ordinary lines.
                    if len(pending) > 65536:
                        log.write(f"{now()} {pending.decode('utf-8', 'replace')}\n")
                        pending = b""
                    log.flush()
                if pending:
                    log.write(f"{now()} {pending.decode('utf-8', 'replace')}\n")
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.stop_event.set()

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join(timeout=2)
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.previous)
        except OSError as exc:
            self.error = self.error or str(exc)
        finally:
            os.close(self.fd)


class Panel:
    def __init__(self, directory: Path):
        self.directory = directory
        self.ssh = ["ssh", "-F", str(SSH_CONFIG), "-o", "BatchMode=yes", "-o",
                    "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=4", "-o",
                    "ConnectionAttempts=1", "-o", "ServerAliveInterval=3", "-o",
                    "ServerAliveCountMax=2", "touch10"]

    def run(self, script: str, timeout: float = 12) -> subprocess.CompletedProcess:
        result = subprocess.run(self.ssh + ["sh -s"], input=script, text=True,
                                capture_output=True, timeout=timeout)
        with (self.directory / "ssh.stderr").open("a") as log:
            log.write(f"{now()} exit={result.returncode}\n{result.stderr}")
        return result

    def snapshot(self) -> dict[str, str]:
        result = self.run(SNAPSHOT)
        if result.returncode:
            raise RuntimeError(f"SSH inspection failed ({result.returncode}); see ssh.stderr")
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if fields.get("uid") != "0":
            raise RuntimeError("Pinned SSH target did not return root")
        uuid.UUID(fields.get("boot_id", ""))
        return fields

    def env_hash(self) -> str:
        # Stock BusyBox has no sha256sum; hash a bounded read on the PC.
        result = subprocess.run(self.ssh + ["dd if=/dev/mmcblk0p8 bs=262144 count=1"],
                                capture_output=True, timeout=15)
        with (self.directory / "ssh.stderr").open("a") as log:
            log.write(f"{now()} environment read exit={result.returncode}\n" +
                      result.stderr.decode("utf-8", "replace"))
        if result.returncode or len(result.stdout) != 262144:
            raise RuntimeError("Cannot read the stock U-Boot environment hash")
        return hashlib.sha256(result.stdout).hexdigest()

    def stage_ram(self, files: dict[str, Path]) -> str:
        remote = "/tmp/touch10-dev-" + uuid.uuid4().hex
        result = self.run("set -eu\n[ \"$(awk '$2 == \"/tmp\" {print $3}' /proc/mounts)\" = tmpfs ]\n"
                          f"umask 077\nmkdir {remote}\n")
        if result.returncode:
            raise RuntimeError("Cannot establish a private tmpfs staging directory")
        manifest = {}
        try:
            for name, path in files.items():
                if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
                    raise ValueError("Unsafe RAM artifact basename")
                content = path.read_bytes()
                if not 0 < len(content) <= 64 * 1024 * 1024:
                    raise ValueError("RAM artifact size is outside the reviewed limit")
                destination = remote + "/" + name
                result = subprocess.run(self.ssh + [f"cat > {destination}"], input=content,
                                        capture_output=True, timeout=120)
                if result.returncode:
                    raise RuntimeError("RAM upload failed")
                verify = subprocess.run(self.ssh + [f"cat {destination}"],
                                        capture_output=True, timeout=120)
                if verify.returncode or verify.stdout != content:
                    write_json(self.directory / "ram-transfer-error.json", {
                        "name": name, "expected_bytes": len(content),
                        "received_bytes": len(verify.stdout), "exit": verify.returncode,
                        "expected_sha256": hashlib.sha256(content).hexdigest(),
                        "received_sha256": hashlib.sha256(verify.stdout).hexdigest(),
                        "stderr": verify.stderr.decode("utf-8", "replace")})
                    raise RuntimeError("RAM upload readback differs from local artifact: " + name)
                manifest[name] = {"source": str(path), "size": len(content),
                                  "sha256": hashlib.sha256(content).hexdigest(), "remote": destination}
            if self.run(f"chmod 700 {remote}/kexec\n").returncode:
                raise RuntimeError("Cannot make the RAM loader executable")
            write_json(self.directory / "ram-artifacts.json", manifest)
            return remote
        except BaseException:
            self.remove_stage(remote, list(files))
            raise

    def remove_stage(self, remote: str, names: list[str]) -> None:
        if not remote.startswith("/tmp/touch10-dev-") or not remote.removeprefix("/tmp/touch10-dev-").isalnum():
            raise ValueError("Unsafe RAM staging path")
        paths = " ".join(shlex.quote(remote + "/" + name) for name in names)
        if self.run(f"rm -f -- {paths}\nrmdir -- {shlex.quote(remote)}\n").returncode:
            raise RuntimeError("RAM staging cleanup failed")


def kexec_load_check(panel: Panel, report: dict) -> None:
    if report["before"].get("kexec_loaded") != "0":
        raise RuntimeError("A kexec image is already loaded; refusing to replace it")
    files = {"kexec": ROOT / "development/ram/kexec-qualified",
             "zImage": ROOT / "development/stock-kernel/ce990-zImage",
             "initramfs.gz": ROOT / "development/stock-kernel/ce990-initramfs.cpio.gz"}
    if hashlib.sha256(files["kexec"].read_bytes()).hexdigest() != KEXEC_LOADER_SHA256:
        raise RuntimeError("Kexec loader differs from reviewed binary")
    for name, expected in {
        "zImage": "88d7702ce52dbe2aa4e9e8634737654b5e49eb10e6e42e34f3c491494e9d6a8e",
        "initramfs.gz": "8d442f2fb6107d73b8f08188070dbfb7cae3708092b8bfa3c4a3b6fe490cc36b",
    }.items():
        if hashlib.sha256(files[name].read_bytes()).hexdigest() != expected:
            raise RuntimeError("Stock load-check image differs from extracted factory image")
    remote = panel.stage_ram(files)
    try:
        script = f'''set -eu
{remote}/kexec --version
[ "$(cat /sys/kernel/kexec_loaded)" = 0 ]
{remote}/kexec --kexec-syscall --load --type=zImage --atags \\
  --mem-min=0x80000000 --mem-max=0x98ffffff --image-size=0x02000000 \\
  --initrd={remote}/initramfs.gz --append="$(cat /proc/cmdline)" {remote}/zImage
[ "$(cat /sys/kernel/kexec_loaded)" = 1 ]
printf 'KEXEC_LOADED=1\\n'
'''
        result = panel.run(script, timeout=60)
        (panel.directory / "kexec-load.log").write_text(result.stdout + result.stderr)
        if result.returncode or "KEXEC_LOADED=1" not in result.stdout:
            raise RuntimeError("Stock kexec load check failed; see kexec-load.log")
        report["kexec_load"] = "passed"
    finally:
        unload = panel.run(f"{remote}/kexec --kexec-syscall --unload\ncat /sys/kernel/kexec_loaded\n")
        report["kexec_unload"] = "passed" if unload.returncode == 0 and unload.stdout.strip() == "0" else "failed"
        panel.remove_stage(remote, list(files))
    if report["kexec_unload"] != "passed":
        raise RuntimeError("Kexec unload did not return to the unloaded state")


def perrier_files(simpledrm: bool = False, lcd: bool = False,
                  native: bool = False) -> dict[str, Path]:
    candidate = ROOT / ("development/perrier-native" if native else
                        "development/perrier-lcd" if lcd else
                        "development/perrier-simpledrm" if simpledrm else "development/perrier")
    review = json.loads((candidate / "reviewed-trial.json").read_text())
    allowed = tuple(f"6.18.48-perrier-ram{version:02d}" for version in range(20, 44)) if native else ("6.18.48-perrier-ram19",) if lcd else tuple(f"6.18.48-perrier-ram{version:02d}" for version in (15, 16, 17, 18)) if simpledrm else tuple(
        f"6.18.48-perrier-ram{version:02d}" for version in range(1, 15))
    if not review.get("passed") or review.get("kernel") not in allowed:
        raise RuntimeError("Perrier trial has no passing artifact audit")
    files = {"kexec": ROOT / "development/perrier/kexec-legacy-fdt",
             "zImage": candidate / "build/arch/arm/boot/zImage",
             "board.dtb": candidate / "build/omap4-perrier-ram.dtb"}
    for name, path in files.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != review["artifacts"][name]["sha256"]:
            raise RuntimeError("Perrier artifact changed after audit: " + name)
    if hashlib.sha256(files["kexec"].read_bytes()).hexdigest() != PERRIER_LOADER_SHA256:
        raise RuntimeError("Perrier loader differs from reviewed binary")
    return files


def perrier_load_script(remote: str) -> str:
    return f'''TOUCH10_LEGACY_ARM_FDT=1 {remote}/kexec --kexec-syscall --load --type=zImage \\
  --mem-min=0x80000000 --mem-max=0x98ffffff --image-size=0x02000000 \\
  --dtb={remote}/board.dtb {remote}/zImage
[ "$(cat /sys/kernel/kexec_loaded)" = 1 ]
'''


def display_handoff_check(panel: Panel, report: dict) -> None:
    """Require the three observed Phoenix buffers and an enabled GFX plane."""
    result = panel.run('''set -eu
mounted=0
if ! grep -q ' /sys/kernel/debug debugfs ' /proc/mounts; then
    mount -t debugfs -o ro debugfs /sys/kernel/debug
    mounted=1
fi
trap '[ "$mounted" = 0 ] || umount /sys/kernel/debug' EXIT
cat /sys/kernel/debug/dri/0/fb
grep -E 'DISPC_OVL_BA0\\(GFX\\)|DISPC_OVL_ATTRIBUTES\\(GFX\\)|DISPC_CONTROL[[:space:]]' /sys/kernel/debug/omapdss/dispc
''', timeout=25)
    if result.returncode:
        raise RuntimeError("Cannot inspect factory display handoff; see ssh.stderr")
    buffers = set(re.findall(r'user fb: 1280x800@AR24\s+0: [^\r\n]*?\b(7[0-9a-f]{7})\b', result.stdout))
    expected = {'7ec78000', '7f060000', '7f448000'}
    plane = re.search(r'DISPC_OVL_BA0\(GFX\)\s+([0-9a-f]{8})', result.stdout)
    attr = re.search(r'DISPC_OVL_ATTRIBUTES\(GFX\)\s+([0-9a-f]{8})', result.stdout)
    control = re.search(r'DISPC_CONTROL\s+([0-9a-f]{8})', result.stdout)
    report['display_handoff'] = {'buffers': sorted(buffers),
                                 'active': plane[1] if plane else None,
                                 'attributes': attr[1] if attr else None,
                                 'control': control[1] if control else None}
    if (buffers != expected or not plane or plane[1] not in expected or
            not attr or not int(attr[1], 16) & 1 or
            not control or not int(control[1], 16) & 1):
        raise RuntimeError("Factory scanout differs from reviewed three-buffer handoff")


def perrier_load_check(panel: Panel, report: dict, simpledrm: bool = False,
                       lcd: bool = False, native: bool = False) -> None:
    if report["before"].get("kexec_loaded") != "0":
        raise RuntimeError("A kexec image is already loaded")
    files = perrier_files(simpledrm, lcd, native)
    remote = panel.stage_ram(files)
    try:
        result = panel.run("set -eu\n" + perrier_load_script(remote) + "printf 'PERRIER_LOADED=1\\n'\n", timeout=60)
        (panel.directory / "perrier-load.log").write_text(result.stdout + result.stderr)
        if result.returncode or "PERRIER_LOADED=1" not in result.stdout:
            raise RuntimeError("Perrier load check failed")
        report["perrier_load"] = "passed"
    finally:
        result = panel.run(f"{remote}/kexec --kexec-syscall --unload\ncat /sys/kernel/kexec_loaded\n")
        report["perrier_unload"] = "passed" if result.returncode == 0 and result.stdout.strip() == "0" else "failed"
        panel.remove_stage(remote, list(files))
    if report["perrier_unload"] != "passed":
        raise RuntimeError("Perrier unload check failed")


def armed_watchdog_request(panel: Panel, report: dict, execute: bool, perrier: bool = False,
                           simpledrm: bool = False, lcd: bool = False,
                           native: bool = False,
                           candidate_files: dict[str, Path] | None = None) -> subprocess.CompletedProcess:
    if report["before"].get("kexec_loaded") != "0":
        raise RuntimeError("A kexec image is already loaded")
    files = {"kexec": ROOT / "development/ram/kexec-qualified",
             "arm-watchdog": ROOT / "development/ram/arm-watchdog"}
    if perrier:
        files.update(candidate_files if candidate_files is not None else
                     perrier_files(simpledrm, lcd, native))
    if hashlib.sha256(files["arm-watchdog"].read_bytes()).hexdigest() != ARM_WATCHDOG_SHA256:
        raise RuntimeError("Watchdog helper differs from reviewed binary")
    if hashlib.sha256(files["kexec"].read_bytes()).hexdigest() != (PERRIER_LOADER_SHA256 if perrier else KEXEC_LOADER_SHA256):
        raise RuntimeError("Kexec loader differs from reviewed binary")
    if execute:
        if not perrier:
            files["stall.zImage"] = ROOT / "development/ram/kexec-stall.zImage"
            if hashlib.sha256(files["stall.zImage"].read_bytes()).hexdigest() != KEXEC_STALL_SHA256:
                raise RuntimeError("RAM stall image differs from reviewed binary")
        prerequisites = []
        for path in sorted((ROOT / "development/runs").glob("*/result.json")):
            previous = json.loads(path.read_text())
            if (previous.get("command") == "watchdog-close-recovery" and previous.get("status") == "passed"
                    and previous.get("environment_after") == STOCK_ENV_SHA256):
                prerequisites.append(str(path))
        if not prerequisites:
            raise RuntimeError("Closed-descriptor watchdog recovery must pass before kexec execution")
        report["watchdog_close_proof"] = prerequisites[-1]
        if perrier:
            qualified = []
            for path in sorted((ROOT / "development/runs").glob("*/result.json")):
                prior = json.loads(path.read_text())
                if prior.get("command") == "kexec-watchdog" and prior.get("status") == "passed" and prior.get("stall_marker_seen"):
                    qualified.append(str(path))
            if not qualified:
                raise RuntimeError("Kexec watchdog entry must be qualified before a kernel trial")
            report["kexec_watchdog_proof"] = qualified[-1]
    remote = panel.stage_ram(files)
    report["ram_stage"] = remote
    load = ""
    if execute:
        load = f'''{remote}/kexec --kexec-syscall --load --type=zImage --atags \\
  --mem-min=0x80000000 --mem-max=0x98ffffff --image-size=0x00100000 \\
  --append="$(cat /proc/cmdline)" {remote}/stall.zImage
[ "$(cat /sys/kernel/kexec_loaded)" = 1 ]
'''
    if perrier:
        load = perrier_load_script(remote)
    duration, guard = (120, 150) if execute else (15, 45)
    request = f'''set -eu
chmod 700 {remote}/arm-watchdog
{load}
set -- $(pidof watchdog)
[ "$#" -eq 1 ]
pid=$1
[ "$(cat /proc/$pid/comm)" = watchdog ]
[ "$(readlink /proc/$pid/exe)" = /bin/watchdog ]
found=no
for fd in /proc/$pid/fd/*; do
    if [ "$(readlink "$fd")" = /dev/watchdog ]; then found=yes; fi
done
[ "$found" = yes ]
nohup sh -c 'sleep {guard}; pidof watchdog >/dev/null || exec /bin/watchdog' </dev/null >/dev/null 2>&1 &
printf 'restart_guard_pid=%s\\n' "$!"
sync
kill -KILL "$pid"
for attempt in 1 2 3 4 5; do
    [ ! -d /proc/$pid/fd ] && break
    sleep 1
done
if ! {remote}/arm-watchdog {duration}; then
    /bin/watchdog </dev/null >/dev/null 2>&1 &
    {remote}/kexec --kexec-syscall --unload || true
    exit 1
fi
'''
    if execute:
        request += f'''printf 'KEXEC_STALL_REQUESTED\\n'
if {remote}/kexec --kexec-syscall --exec; then :; fi
/bin/watchdog </dev/null >/dev/null 2>&1 &
{remote}/kexec --kexec-syscall --unload || true
exit 1
'''
    result = panel.run(request, timeout=30)
    (panel.directory / "watchdog-request.log").write_text(result.stdout + result.stderr)
    return result


def wait_for_stock(panel, previous: dict[str, str], timeout: float, interval: float = 2,
                   monotonic=time.monotonic, sleep=time.sleep) -> dict[str, str]:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        try:
            current = panel.snapshot()
            if current["hostname"] != previous["hostname"]:
                raise ValueError("SSH hostname changed; refusing to identify this as the panel")
            if (current["boot_id"] != previous["boot_id"] and
                    current["kernel"] == previous["kernel"] and
                    current.get("factory_app") == "running"):
                return current
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        sleep(min(interval, max(0, deadline - monotonic())))
    raise TimeoutError("Stock firmware did not return with a new boot ID; stopped without retrying reboot")


def host_checks() -> dict:
    checks = {}
    for key, command in {
        "link": ["ip", "-j", "address", "show", "dev", "enp7s0"],
        "dhcp_service": ["systemctl", "is-active", "touch10-dev-dhcp.service"],
    }.items():
        result = subprocess.run(command, text=True, capture_output=True, timeout=8)
        checks[key] = {"exit": result.returncode, "stdout": result.stdout.strip(),
                       "stderr": result.stderr.strip()}
    return checks


def validate_host(checks: dict) -> None:
    if checks["dhcp_service"]["exit"] or checks["dhcp_service"]["stdout"] != "active":
        raise RuntimeError("Dedicated Touch 10 DHCP service is not active")
    if checks["link"]["exit"]:
        raise RuntimeError("Cannot inspect the Touch 10 Ethernet interface")
    links = json.loads(checks["link"]["stdout"])
    if not links or "LOWER_UP" not in links[0].get("flags", []):
        raise RuntimeError("Touch 10 Ethernet cable has no carrier")
    if not any(a.get("local") == "10.77.10.1" and a.get("prefixlen") == 24
               for a in links[0].get("addr_info", [])):
        raise RuntimeError("Touch 10 interface lacks 10.77.10.1/24")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=UART)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="read-only host/panel preflight and passive UART check")
    sub.add_parser("kexec-load-check", help="load/unload the exact stock kernel in RAM without executing it")
    sub.add_parser("perrier-load-check", help="load/unload the audited minimal kernel and FDT trampoline")
    drm_load = sub.add_parser("perrier-simpledrm-load-check", help="load/unload an audited DRM RAM candidate")
    drm_load.add_argument("--candidate", choices=("simpledrm", "lcd", "native"), default="simpledrm")
    capture = sub.add_parser("capture", help="passively record UART; sends no bytes")
    capture.add_argument("--seconds", type=float, default=600)
    reboot = sub.add_parser("reboot-stock", help="one software reboot and verify stock firmware returns")
    reboot.add_argument("--timeout", type=float, default=600)
    watchdog = sub.add_parser("watchdog-recovery", help="pause the existing feeder once, with a 90-second resume guard")
    watchdog.add_argument("--timeout", type=float, default=600)
    closed = sub.add_parser("watchdog-close-recovery", help="arm 15 seconds then close the fd; observe one automatic reset")
    closed.add_argument("--timeout", type=float, default=600)
    stall = sub.add_parser("kexec-watchdog", help="execute only the reviewed RAM stall image with a 120-second watchdog")
    stall.add_argument("--timeout", type=float, default=600)
    trial = sub.add_parser("perrier-trial", help="execute the audited serial-only Perrier kernel and wait for watchdog recovery")
    trial.add_argument("--timeout", type=float, default=600)
    drm_trial = sub.add_parser("perrier-simpledrm-trial", help="execute the audited ram15 simpledrm candidate and verify stock recovery")
    drm_trial.add_argument("--timeout", type=float, default=600)
    drm_trial.add_argument("--candidate", choices=("simpledrm", "lcd", "native"), default="simpledrm")
    args = parser.parse_args()
    if getattr(args, "seconds", 1) <= 0 or getattr(args, "timeout", 1) <= 0:
        parser.error("time limits must be positive")
    if args.command == "watchdog-recovery" and args.timeout < 150:
        parser.error("watchdog recovery timeout must exceed the 90-second resume guard (minimum 150)")
    if args.command in ("watchdog-close-recovery", "kexec-watchdog", "perrier-trial", "perrier-simpledrm-trial") and args.timeout < 240:
        parser.error("armed watchdog recovery timeout must be at least 240 seconds")
    os.umask(0o077)
    base = ROOT / "development"
    base.mkdir(exist_ok=True)
    with (base / ".runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(2, "Another Touch 10 development run is active\n")
        directory = base / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
                                     "-" + args.command + "-" + uuid.uuid4().hex[:6])
        directory.mkdir(parents=True)
        report = {"command": args.command, "started": now(), "status": "running",
                  "port": args.port, "logs": str(directory)}
        write_json(directory / "result.json", report)
        print(f"Logs: {directory}", flush=True)
        serial = None
        try:
            with SerialCapture(args.port, directory) as serial:
                if args.command == "capture":
                    serial.stop_event.wait(args.seconds)
                else:
                    report["host"] = host_checks()
                    validate_host(report["host"])
                    panel = Panel(directory)
                    previous = panel.snapshot()
                    report["before"] = previous
                    report["environment_before"] = panel.env_hash()
                    if report["environment_before"] != STOCK_ENV_SHA256:
                        raise RuntimeError("Boot environment differs from the verified normal-boot state; review before reboot")
                    write_json(directory / "result.json", report)
                    if args.command in ("kexec-load-check", "perrier-load-check", "perrier-simpledrm-load-check"):
                        if args.command == "kexec-load-check":
                            kexec_load_check(panel, report)
                        else:
                            perrier_load_check(panel, report,
                                               args.command == "perrier-simpledrm-load-check",
                                               getattr(args, "candidate", None) == "lcd",
                                               getattr(args, "candidate", None) == "native")
                        report["after"] = panel.snapshot()
                        report["environment_after"] = panel.env_hash()
                        if (report["after"]["boot_id"] != previous["boot_id"] or
                                report["environment_after"] != report["environment_before"]):
                            raise RuntimeError("Unexpected state change during load/unload check")
                    if args.command in ("reboot-stock", "watchdog-recovery", "watchdog-close-recovery", "kexec-watchdog", "perrier-trial", "perrier-simpledrm-trial"):
                        if previous["kernel"] != "3.4.113+" or previous.get("factory_app") != "running":
                            raise RuntimeError("Stock reboot test requires the known factory kernel and phoenix")
                        if args.command == "perrier-simpledrm-trial" or args.command == "perrier-trial" and json.loads(
                                (ROOT / "development/perrier/reviewed-trial.json").read_text()).get("kernel") in (
                                    "6.18.48-perrier-ram12", "6.18.48-perrier-ram13",
                                    "6.18.48-perrier-ram14"):
                            display_handoff_check(panel, report)
                        print(f"Starting {args.command}; watching serial and key-only SSH", flush=True)
                        report["reboot_requested_at"] = now()
                        write_json(directory / "result.json", report)
                        # Exactly one request; never escalates to force-reboot or repeated resets.
                        try:
                            if args.command in ("watchdog-close-recovery", "kexec-watchdog", "perrier-trial", "perrier-simpledrm-trial"):
                                result = armed_watchdog_request(panel, report,
                                    args.command != "watchdog-close-recovery",
                                    args.command in ("perrier-trial", "perrier-simpledrm-trial"),
                                    args.command == "perrier-simpledrm-trial",
                                    getattr(args, "candidate", None) == "lcd",
                                    getattr(args, "candidate", None) == "native")
                            else:
                                result = panel.run("reboot\n" if args.command == "reboot-stock" else WATCHDOG_RECOVERY, timeout=20)
                            report["reboot_ssh_exit"] = result.returncode
                            report["request_stdout"] = result.stdout
                            if result.returncode not in (0, 255):
                                raise RuntimeError(f"Reboot command returned {result.returncode}")
                        except subprocess.TimeoutExpired:
                            report["reboot_ssh_timeout"] = True
                        write_json(directory / "result.json", report)
                        report["after"] = wait_for_stock(panel, previous, args.timeout)
                        report["environment_after"] = panel.env_hash()
                        if report["environment_before"] != report["environment_after"]:
                            raise RuntimeError("U-Boot environment hash changed across reboot")
                        serial.stop_event.wait(2)
                        if args.command == "kexec-watchdog":
                            report["stock_recovered"] = True
                            report["stall_marker_seen"] = b"TOUCH10_KEXEC_RAM_STALL" in (directory / "serial.raw").read_bytes()
                            if not report["stall_marker_seen"]:
                                raise RuntimeError("Stock recovered, but the RAM payload entry marker was not captured")
                        if args.command in ("perrier-trial", "perrier-simpledrm-trial"):
                            data = (directory / "serial.raw").read_bytes()
                            report["stock_recovered"] = True
                            # Console printk may interleave with the READY write.
                            # ENTER plus multiple timed ticks proves PID 1 ran.
                            report["kernel_init_ready"] = any(
                                f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data
                                for version in range(1, 44))
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(3, 44)):
                                report["mmc_cid_matches_stock"] = (
                                    b"11010030303447413002265429a4c587" in data)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(4, 44)):
                                report["mmc_crc32_matches_backup"] = (
                                    re.search(rb"PERRIER_MMC_P1_CRC32.{0,512}?match=1", data, re.DOTALL) is not None)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(5, 44)):
                                report["stock_base_readonly"] = (
                                    b"PERRIER_DIR /mnt/base " in data and
                                    b"PERRIER_BASE_RDONLY result=0 ro=1 errno=0" in data and
                                    b"ce9.9.0 46f7ea38fda" in data)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(6, 44)):
                                report["stock_squashfs_readonly"] = all(
                                    f"PERRIER_SQUASH_MOUNT name={name} result=0 errno=0 loop_ro=1 fs_ro=1".encode() in data
                                    for name in ("extra", "gui", "apps"))
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(7, 44)):
                                report["stock_squashfs_xattrs"] = (
                                    b"Xattrs in filesystem" not in data and
                                    b"unable to read xattr id index table" not in data)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(8, 44)):
                                report["i2c2_adapter_only"] = (
                                    b"PERRIER_I2C2_ADAPTER matched=1 name=OMAP I2C adapter" in data)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(10, 44)):
                                report["i2c3_adapter_only"] = (
                                    b"PERRIER_I2C3_ADAPTER matched=1 name=OMAP I2C adapter" in data)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(11, 44)):
                                report["touch_header_read"] = (
                                    re.search(rb"PERRIER_TOUCH_HEADER count=16 errno=0 data=[0-9a-f]{32}", data) is not None)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(12, 15)):
                                report["simplefb_registered"] = (
                                    b"simplefb registered!" in data and
                                    b"PERRIER_DIR /sys/class/graphics" in data and
                                    re.search(rb"FILE.{0,128}/sys/class/graphics/fb0/name", data, re.DOTALL) is not None)
                            if b"PERRIER_INIT_ENTER ram13" in data or b"PERRIER_INIT_ENTER ram14" in data:
                                report["framebuffer_pixel_test"] = (
                                    b"PERRIER_FB_MARKER_WRITTEN readback=1" in data and
                                    b"PERRIER_FB_MARKER_RESTORED readback=1" in data)
                            if b"PERRIER_INIT_ENTER ram14" in data:
                                report["touch_raw_sampled"] = (
                                    b"PERRIER_TOUCH_RAW sample=0 data=" in data and
                                    re.search(rb"PERRIER_TOUCH_RAW_DONE samples=300 changes=\d+ logged=\d+ errors=0", data) is not None)
                                match = re.search(rb"PERRIER_TOUCH_RAW_DONE samples=300 changes=(\d+)", data)
                                report["touch_report_changes"] = int(match[1]) if match else None
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in (15, 16, 17, 18, 19)):
                                report["simpledrm_registered"] = (
                                    b"PERRIER_DIR /dev/dri card0" in data and
                                    b"[drm] Initialized simpledrm" in data and
                                    b"FILE /sys/class/drm/card0-Unknown-1/modes" in data)
                            if any(b"PERRIER_INIT_ENTER ram" + str(version).encode() in data for version in (16, 17, 18, 19)):
                                # printk can split a PID 1 proof line mid-word on UART.
                                kms_data = re.sub(rb"\[[ \t]*\d+\.\d+\] [^\r\n]*\r?\n", b"", data)
                                report["simpledrm_kms_mode"] = (
                                    re.search(rb"PERRIER_DRM_RESOURCES crtcs=1 connectors=1", kms_data) is not None and
                                    re.search(rb"PERRIER_DRM_CONNECTOR id=\d+ connection=1 modes=1", kms_data) is not None and
                                    re.search(rb"PERRIER_DRM_MODE name=1280x800 width=1280 height=800", kms_data) is not None and
                                    b"PERRIER_DRM_PROBE_EXIT status=0" in kms_data)
                            if b"PERRIER_INIT_ENTER ram18" in data:
                                report["touch_one_ack_sent"] = (
                                    re.search(rb"PERRIER_TOUCH_ACK mode_before=(80|00) value=(00|80) bytes=2", data) is not None)
                                report["touch_raw_sampled"] = (
                                    b"PERRIER_TOUCH_WINDOW_START samples=300 period_ms=100" in data and
                                    re.search(rb"PERRIER_TOUCH_RAW_DONE samples=300 changes=\d+ logged=\d+ errors=0", data) is not None)
                                match = re.search(rb"PERRIER_TOUCH_RAW_DONE samples=300 changes=(\d+)", data)
                                report["touch_report_changes"] = int(match[1]) if match else None
                            if b"PERRIER_INIT_ENTER ram19" in data:
                                report["lcd_handoff_guard_rejected"] = b"PERRIER_LCD_GUARD rejected=1" in data
                                report["lcd_manager_enabled"] = b"PERRIER_LCD_ENABLED control=" in data
                                report["lcd_handoff_restored"] = b"PERRIER_LCD_RESTORED control=" in data
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(20, 44)):
                                report["native_drm_card_seen"] = b"PERRIER_DIR /dev/dri card0" in data
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(24, 40)):
                                report["native_pattern_set"] = b"PERRIER_PATTERN_SETCRTC_OK" in data
                                report["native_pattern_window_ended"] = b"PERRIER_PATTERN_WINDOW_END" in data
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(25, 40)):
                                report["native_pattern_active_crtc"] = b"PERRIER_PATTERN_GETCRTC fb=" in data and b" match=1" in data
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(26, 40)):
                                report["native_bridge_stock_regs"] = all(
                                    f"PERRIER_BRIDGE_SNAPSHOT reg={name} value={value}".encode() in data
                                    for name, value in (("VPCTRL", "00f02110"),
                                                        ("LVCFG", "00000001"),
                                                        ("LVPHY0", "00004006")))
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in range(27, 40)):
                                report["native_dsi_snapshot"] = b"PERRIER_DSS_SNAPSHOT file=dsi1_regs DSI_CTRL" in data
                                report["native_backlight_snapshot"] = (
                                    b"PERRIER_BACKLIGHT_SNAPSHOT_END phase=before_modeset status=0" in data and
                                    b"PERRIER_BACKLIGHT_SNAPSHOT_END phase=after_modeset status=0" in data)
                            if any(f"PERRIER_INIT_ENTER ram{version:02d}".encode() in data for version in (40, 41, 42, 43)):
                                report["qt_devices_ready"] = b"PERRIER_QT_DEVICES touch=1 fb=1" in data
                                report["qt_input_bridge_ready"] = b"PERRIER_UINPUT_READY raw_coordinates 1280x800" in data
                                report["qt_ui_ready"] = b"PERRIER_QT_READY touch-grid 1280x800" in data
                                report["qt_ui_exited"] = (b"PERRIER_QT_EXIT status=0" in data and
                                                        b"PERRIER_QT_WAIT status=0" in data)
                                report["qt_touch_reports"] = len(re.findall(rb"PERRIER_UINPUT_TOUCH x=", data))
                            match = re.search(rb"PERRIER_WDT_RUNNING .*delta=(\d+)", data)
                            report["watchdog_counter_delta"] = int(match[1]) if match else 0
                            report["watchdog_tick_samples"] = len(re.findall(rb"PERRIER_WDT_TICK", data))
                            report["software_reboot_requested"] = (
                                b"PERRIER_SOFT_REBOOT_REQUESTED" in data or
                                (b"PERRIER_SOFT_REBOOT_REQU" in data and b"reboot: Restarting system" in data))
                            if (not report["kernel_init_ready"] or report["watchdog_counter_delta"] == 0 or
                                    report["watchdog_tick_samples"] < 2 or not report["software_reboot_requested"] or
                                    b"PERRIER_SOFT_REBOOT_FAILED" in data or b"Kernel panic" in data or
                                    report.get("mmc_cid_matches_stock") is False or
                                    report.get("mmc_crc32_matches_backup") is False or
                                    report.get("stock_base_readonly") is False or
                                    report.get("stock_squashfs_readonly") is False or
                                    report.get("stock_squashfs_xattrs") is False or
                                    report.get("i2c2_adapter_only") is False or
                                    report.get("i2c3_adapter_only") is False or
                                    report.get("touch_header_read") is False or
                                    report.get("simplefb_registered") is False or
                                    report.get("simpledrm_registered") is False or
                                    report.get("simpledrm_kms_mode") is False or
                                    report.get("native_drm_card_seen") is False or
                                    report.get("native_pattern_set") is False or
                                    report.get("native_pattern_window_ended") is False or
                                    report.get("native_pattern_active_crtc") is False or
                                    report.get("native_bridge_stock_regs") is False or
                                    report.get("native_dsi_snapshot") is False or
                                    report.get("native_backlight_snapshot") is False or
                                    report.get("qt_devices_ready") is False or
                                    report.get("qt_input_bridge_ready") is False or
                                    report.get("qt_ui_ready") is False or
                                    report.get("qt_ui_exited") is False or
                                    report.get("touch_one_ack_sent") is False or
                                    report.get("framebuffer_pixel_test") is False or
                                    report.get("touch_raw_sampled") is False):
                                raise RuntimeError("Stock recovered, but kernel/init/watchdog proof is incomplete; inspect serial.log")
                if serial.error:
                    raise RuntimeError(f"Serial capture failed: {serial.error}")
            report["status"] = "passed"
        except (Exception, KeyboardInterrupt) as exc:
            report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            report["error"] = str(exc) or type(exc).__name__
        finally:
            report["finished"] = now()
            if serial:
                report["serial_bytes"] = serial.byte_count
                report["serial_error"] = serial.error
                if serial.error and report["status"] == "passed":
                    report["status"], report["error"] = "failed", serial.error
            write_json(directory / "result.json", report)
        print(f"{report['status'].upper()}: {report.get('error', args.command)}", flush=True)
        return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
