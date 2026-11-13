#!/usr/bin/env python3
"""Capture the owner's Touch 10 codec session request after an authorized pairing.

Uses the same temporary test-codec certificate. It offers the installed
version on 4045 and accepts TLS on 4051. Optional greeting echo is bounded.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import select
import socket
import ssl
import time

VERSION_INFO = b"version: ce9.9.0 46f7ea38fda 2019-10-10\nmethod: none\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--echo-greeting", action="store_true",
                        help="echo only a recognized phoenix/codecquery greeting, then read one follow-up")
    parser.add_argument("--echo-status-query", action="store_true",
                        help="also echo the two observed read-only SystemUnit/State query frames")
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.echo_status_query and not args.echo_greeting:
        parser.error("--echo-status-query requires --echo-greeting")
    if not 1 <= args.seconds <= 900:
        parser.error("--seconds must be 1..900")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1
    context.set_ciphers("DEFAULT:@SECLEVEL=0")
    context.load_cert_chain(str(args.certificate), str(args.private_key))

    listeners = []
    events = []
    echoed = set()
    try:
        for port in (4045, 4051):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((args.host_ip, port))
            listener.listen(4)
            listeners.append(listener)
        mode = "bounded greeting echo" if args.echo_greeting else "passive capture"
        print(f"Test codec session {mode} ready on 4045 and 4051", flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select(listeners, [], [], min(0.5, deadline - time.monotonic()))
            for listener in ready:
                connection, peer = listener.accept()
                with connection:
                    port = listener.getsockname()[1]
                    if peer[0] != args.target_ip:
                        continue
                    event = {"utc": datetime.now(timezone.utc).isoformat(), "port": port}
                    try:
                        connection.settimeout(3)
                        if port == 4045:
                            connection.sendall(VERSION_INFO)
                            event["kind"] = "same_version_no_package"
                        else:
                            with context.wrap_socket(connection, server_side=True) as tls:
                                request = tls.recv(4096)
                                event.update(kind="session_request", tls_version=tls.version(),
                                             request_hex=request.hex(), request_bytes=len(request))
                                greeting_name = ("phoenix" if b"phoenix" in request else
                                                 "codecquery" if b"codecquery" in request else "")
                                if (args.echo_greeting and greeting_name not in echoed and
                                    request[:8] == b"rxhtrths" and
                                    len(request) >= 12 and
                                    int.from_bytes(request[8:12], "big") == len(request) - 12 and
                                    greeting_name):
                                    tls.sendall(request)
                                    echoed.add(greeting_name)
                                    event["response"] = "exact_greeting_echo"
                                    followups = []
                                    status_echoed = False
                                    tls.settimeout(1)
                                    for _ in range(12):
                                        try:
                                            followup = tls.recv(4096)
                                        except TimeoutError:
                                            break
                                        if not followup:
                                            break
                                        followups.append(followup.hex())
                                        if (args.echo_status_query and not status_echoed and
                                            followup.count(b"rxhtrtx1") == 2 and
                                            followup.count(b"Status/SystemUnit/State") == 2):
                                            tls.sendall(followup)
                                            status_echoed = True
                                            event["response_status"] = "exact_status_query_echo"
                                        if sum(len(part) for part in followups) >= 32768:
                                            break
                                    event["followup_hex_chunks"] = followups
                    except (OSError, ssl.SSLError) as error:
                        event.update(kind="error", error_type=type(error).__name__,
                                     error=str(error)[:160])
                    events.append(event)
                    print(json.dumps(event), flush=True)
            if len(echoed) == 2:
                break
    finally:
        for listener in listeners:
            listener.close()
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(json.dumps({"events": events, "software_package_served": False,
                                        "greeting_echo_enabled": args.echo_greeting,
                                        "status_query_echo_enabled": args.echo_status_query}, indent=2) + "\n")


if __name__ == "__main__":
    main()
