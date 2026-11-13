#!/usr/bin/env python3
"""Temporarily replace the direct-link DHCP service with a local DNS fixture.

Run install/restore as root. An independent systemd timer restores the normal
service after 20 minutes if the interactive test is interrupted.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "dnsmasq-route-dns-test.conf"
FIXTURE_SHA256 = "5a00e0e89d06ac2532eb1b94a4467d6c75cb813ac1332978014f9cc5cd8acf94"
NORMAL = Path("/etc/touch10-dev/dnsmasq.conf")
NORMAL_SHA256 = "7bb6ad2f4856ffda481e8ec1f115956deacb35d539c0bd1a6f1dc6f4a9ad97c8"
CONFIG = Path("/run/touch10-route-dns-test.conf")
DROPIN = Path("/run/systemd/system/touch10-dev-dhcp.service.d/80-route-dns-test.conf")
TIMER = "touch10-route-dns-rollback.timer"
SERVICE = "touch10-dev-dhcp.service"
OVERRIDE = (
    "[Service]\n"
    "BindReadOnlyPaths=/home/marius/ext_proj/touch10/development/host/"
    "dnsmasq-route-dns-test.conf:/run/touch10-route-dns-test.conf\n"
    "ExecStart=\n"
    "ExecStart=/usr/bin/dnsmasq --keep-in-foreground "
    "--conf-file=/run/touch10-route-dns-test.conf\n"
)


def run(*args: str, timeout: int = 15) -> str:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active() -> None:
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError(f"{SERVICE} is not active")


def restore() -> None:
    # Never delete an override edited by someone else during the test.
    if DROPIN.exists() and DROPIN.read_text() != OVERRIDE:
        raise RuntimeError(f"unexpected contents in {DROPIN}; refusing to remove it")
    DROPIN.unlink(missing_ok=True)
    CONFIG.unlink(missing_ok=True)
    run("systemctl", "daemon-reload")
    run("systemctl", "restart", SERVICE)
    active()
    # Stopping a timer that already fired is harmless. A later timer run is
    # also idempotent if systemd has already launched its service.
    subprocess.run(("systemctl", "stop", TIMER), capture_output=True, timeout=10)
    # A bind-mount target can be recreated during the old service's stop.
    # Clean it only after the normal service is stably active again.
    time.sleep(1)
    CONFIG.unlink(missing_ok=True)
    print("NORMAL_DHCP_RESTORED", flush=True)


def install() -> None:
    active()
    if digest(NORMAL) != NORMAL_SHA256 or digest(FIXTURE) != FIXTURE_SHA256:
        raise RuntimeError("normal or test dnsmasq configuration differs from review")
    if CONFIG.exists() and not DROPIN.exists() and CONFIG.stat().st_size == 0:
        CONFIG.unlink()
    if DROPIN.exists() or CONFIG.exists():
        raise RuntimeError("a route/DNS fixture is already installed")
    run("dnsmasq", "--test", f"--conf-file={FIXTURE}")
    try:
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text(OVERRIDE)
        DROPIN.chmod(0o644)
        run("systemctl", "daemon-reload")
        run("systemctl", "restart", SERVICE)
        time.sleep(1)
        active()
        run("systemd-run", "--unit=touch10-route-dns-rollback", "--on-active=20m",
            "/usr/bin/python3", str(Path(__file__).resolve()), "restore")
        print("ROUTE_DNS_FIXTURE_READY rollback=20m", flush=True)
    except BaseException:
        restore()
        raise


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("run this host fixture as root")
    if len(sys.argv) != 2 or sys.argv[1] not in {"install", "restore"}:
        raise RuntimeError("usage: route_dns_fixture.py install|restore")
    if sys.argv[1] == "install":
        install()
    else:
        restore()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
