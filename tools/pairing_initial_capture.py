#!/usr/bin/env python3
"""Observe only the first five bytes of a Touch 10 pairing TCP connection.

The listeners never send a byte, request credentials, offer a certificate, or
serve firmware. Each accepted connection is closed after its record header.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import select
import socket
import time


PORTS = (4045, 4053)
NO_PACKAGE_INFO = b"version: N/A\nmethod: none\n"
SAME_VERSION_INFO = b"version: ce9.9.0 46f7ea38fda 2019-10-10\nmethod: none\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=150)
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--no-package-info", action="store_true",
                        help="send only a fixed 'no package available' response on port 4045")
    parser.add_argument("--same-version-info", action="store_true",
                        help="send only this unit's observed CE9.9.0 version on port 4045")
    args = parser.parse_args()
    if args.no_package_info and args.same_version_info:
        parser.error("choose only one version response")
    if not 1 <= args.seconds <= 300:
        parser.error("--seconds must be 1..300")
    for address in (args.host_ip, args.target_ip):
        try:
            socket.inet_aton(address)
        except OSError:
            parser.error(f"invalid IPv4 address: {address}")

    listeners = []
    events = []
    try:
        for port in PORTS:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((args.host_ip, port))
            listener.listen(2)
            listeners.append(listener)
        print("Listening on 4045 and 4053; no firmware service", flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select(listeners, [], [],
                                        min(0.5, deadline - time.monotonic()))
            for listener in ready:
                conn, peer = listener.accept()
                with conn:
                    if peer[0] != args.target_ip:
                        continue
                    version_response = listener.getsockname()[1] == 4045 and (
                        args.no_package_info or args.same_version_info)
                    if version_response:
                        conn.sendall(SAME_VERSION_INFO if args.same_version_info
                                     else NO_PACKAGE_INFO)
                        header = b""
                    else:
                        conn.settimeout(2)
                        try:
                            header = conn.recv(5)
                        except socket.timeout:
                            header = b""
                    kind = "tls_client_hello" if (len(header) == 5 and
                        header[0] == 0x16 and header[1] == 0x03) else "other"
                    event = {"utc": datetime.now(timezone.utc).isoformat(),
                             "port": listener.getsockname()[1],
                             "source": peer[0], "source_port": peer[1],
                             "first_record_bytes": len(header), "kind": kind,
                             "version_response": ("same_version" if args.same_version_info
                                else "no_package") if version_response else None}
                    events.append(event)
                    print(json.dumps(event), flush=True)
    finally:
        for listener in listeners:
            listener.close()
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(json.dumps({"host_ip": args.host_ip,
                                        "target_ip": args.target_ip,
                                        "ports": PORTS,
                                        "no_package_info": args.no_package_info,
                                        "same_version_info": args.same_version_info,
                                        "seconds": args.seconds,
                                        "events": events}, indent=2) + "\n")
    print(f"Captured {len(events)} initial connections", flush=True)


if __name__ == "__main__":
    main()
