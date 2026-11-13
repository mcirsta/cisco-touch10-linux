#!/usr/bin/env python3
"""Compile/check one pinned ROM probe and, explicitly, capture one live upload.

``--check pass|stall`` is entirely offline. ``--run pass|stall`` opens the
Touch 10 FTDI service console passively before the C uploader waits for a
cold-boot ROM USB enumeration. The console is never written to. Each run
creates timestamped USB, serial, and event logs and keeps serial capture for
120 seconds after the one upload attempt finishes.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import termios
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/rom_speedup_poll_probe.c"
RUNS = ROOT / "evidence/bootrom-speedup-poll-2026-11-07/runs"
SERIAL = Path("/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0")
FTDI_SYSFS = Path("/sys/bus/usb/devices/2-1.1.1")
POST_CAPTURE_SECONDS = 120


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def verify_ftdi() -> None:
    expected = {"idVendor": "0403", "idProduct": "6015", "serial": "D3081QEX"}
    for name, value in expected.items():
        try:
            actual = (FTDI_SYSFS / name).read_text().strip()
        except OSError as exc:
            raise RuntimeError(f"FTDI sibling {FTDI_SYSFS} is unavailable: {exc}") from exc
        if actual.lower() != value.lower():
            raise RuntimeError(f"FTDI sibling {name} mismatch: {actual!r}")
    try:
        target = SERIAL.resolve(strict=True)
        tty_device = (Path("/sys/class/tty") / target.name / "device").resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Pinned FTDI serial port is unavailable: {exc}") from exc
    if not re.fullmatch(r"ttyUSB\d+", target.name) or "2-1.1.1:1.0" not in str(tty_device):
        raise RuntimeError(f"Serial port is not the pinned FTDI sibling: {target} / {tty_device}")


class SerialCapture:
    """Read-only FTDI capture, following the known serial_probe.py settings."""

    def __init__(self, folder: Path) -> None:
        self.fd = os.open(SERIAL, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self.previous = termios.tcgetattr(self.fd)
        except BaseException:
            os.close(self.fd)
            raise
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self.raw = None
        self.lines = None
        self.thread = None
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = 0
            attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[3] = 0
            attrs[4] = attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            self.raw = (folder / "serial.raw").open("wb")
            self.lines = (folder / "serial.txt").open("w", encoding="utf-8", buffering=1)
            self.thread = threading.Thread(target=self._capture, name="touch10-serial", daemon=True)
            self.thread.start()
        except BaseException:
            self.close()
            raise

    def _capture(self) -> None:
        pending = bytearray()
        try:
            while not self.stop.is_set():
                ready, _, _ = select.select([self.fd], [], [], 0.2)
                if not ready:
                    continue
                data = os.read(self.fd, 65536)
                if not data:
                    continue
                self.raw.write(data)
                self.raw.flush()
                pending.extend(data)
                while b"\n" in pending:
                    end = pending.index(0x0A) + 1
                    line = bytes(pending[:end])
                    del pending[:end]
                    self.lines.write(f"{utc()} {line.decode('utf-8', 'backslashreplace')}")
                if len(pending) >= 4096:
                    self.lines.write(f"{utc()} {bytes(pending).decode('utf-8', 'backslashreplace')}\n")
                    pending.clear()
        except BaseException as exc:
            self.error = exc
        finally:
            if pending:
                self.lines.write(f"{utc()} {bytes(pending).decode('utf-8', 'backslashreplace')}\n")

    def close(self) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.previous)
        finally:
            os.close(self.fd)
            if self.raw is not None:
                self.raw.close()
            if self.lines is not None:
                self.lines.close()

    def __enter__(self) -> SerialCapture:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_binary(folder: Path) -> Path:
    binary = folder / "rom_speedup_poll_probe"
    command = [
        "cc", "-std=c11", "-D_DEFAULT_SOURCE", "-O2", "-Wall", "-Wextra", "-Werror",
        str(SOURCE), "-o", str(binary), "-lcrypto",
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    return binary


def run_live(binary: Path, variant: str) -> int:
    verify_ftdi()
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix=f"{stamp}-{variant}-", dir=RUNS))
    print(f"Logs: {folder}", flush=True)
    with (folder / "events.log").open("w", encoding="utf-8", buffering=1) as events:
        def event(message: str) -> None:
            record = f"{utc()} {message}"
            events.write(record + "\n")
            print(record, flush=True)

        event(f"variant={variant}; fixed USB path=2-1.1.2; passive FTDI={SERIAL}")
        with SerialCapture(folder) as serial:
            event("Passive serial capture ready; no serial bytes will be sent")
            process = None
            try:
                with (folder / "usb.log").open("w", encoding="utf-8", buffering=1) as usb_log:
                    process = subprocess.Popen(
                        [str(binary), "--run", variant], cwd=ROOT,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1,
                    )
                    event(f"USB uploader started, pid={process.pid}; waiting for its readiness marker")
                    assert process.stdout is not None
                    for line in process.stdout:
                        usb_log.write(line)
                        print(line, end="", flush=True)
                        if "Ready: waiting up to" in line:
                            event("Serial capture and pinned USB wait ready; one cold power cycle may begin")
                        if "Opened pinned 2-1.1.2" in line:
                            event("Observed TI ROM enumeration on the pinned USB port after cold power cycle")
                    result = process.wait()
                event(f"USB uploader exited with status {result}")
                deadline = time.monotonic() + POST_CAPTURE_SECONDS
                event(f"Keeping serial capture for {POST_CAPTURE_SECONDS} more seconds")
                while time.monotonic() < deadline:
                    if serial.error is not None:
                        raise RuntimeError(f"Serial capture failed: {serial.error}")
                    time.sleep(min(0.2, deadline - time.monotonic()))
                event("Post-transfer serial capture complete")
                if serial.error is not None:
                    raise RuntimeError(f"Serial capture failed: {serial.error}")
                return result
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", choices=("pass", "stall"), metavar="{pass,stall}",
                      help="compile and verify one image entirely offline")
    mode.add_argument("--run", choices=("pass", "stall"), metavar="{pass,stall}",
                      help="capture and upload exactly one image on the next cold boot")
    args = parser.parse_args()
    variant = args.check or args.run
    with tempfile.TemporaryDirectory(prefix="touch10-rom-speedup-build-") as temp:
        binary = build_binary(Path(temp))
        subprocess.run([str(binary), "--check", variant], cwd=ROOT, check=True)
        if args.run:
            return run_live(binary, variant)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Probe aborted: {exc}", file=sys.stderr)
        raise SystemExit(1)
