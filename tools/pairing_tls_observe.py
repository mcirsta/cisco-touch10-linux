#!/usr/bin/env python3
"""Observe one Touch 10 pairing request over TLS without completing pairing."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import select
import socket
import ssl
import subprocess
import tempfile
import time


VERSION_INFO = b"version: ce9.9.0 46f7ea38fda 2019-10-10\nmethod: none\n"


def event(kind, **fields):
    return {"utc": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error("--seconds must be 1..300")
    for address in (args.host_ip, args.target_ip):
        socket.inet_aton(address)

    events = []
    with tempfile.TemporaryDirectory(prefix="touch10-tls-") as directory:
        certificate = Path(directory) / "certificate.pem"
        private_key = Path(directory) / "private-key.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(private_key), "-out", str(certificate), "-days", "1",
             "-subj", "/CN=Touch10 local test codec"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1
        context.set_ciphers("DEFAULT:@SECLEVEL=0")
        context.load_cert_chain(str(certificate), str(private_key))

        listeners = []
        try:
            for port in (4045, 4053):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((args.host_ip, port))
                listener.listen(2)
                listeners.append(listener)
            print("Listening on 4045 and TLS 4053; no package, credentials, or pairing acceptance", flush=True)
            deadline = time.monotonic() + args.seconds
            observed_request = False
            while time.monotonic() < deadline and not observed_request:
                ready, _, _ = select.select(listeners, [], [],
                                            min(0.5, deadline - time.monotonic()))
                for listener in ready:
                    connection, peer = listener.accept()
                    with connection:
                        port = listener.getsockname()[1]
                        if peer[0] != args.target_ip:
                            events.append(event("ignored_peer", port=port, source=peer[0]))
                            continue
                        if port == 4045:
                            connection.sendall(VERSION_INFO)
                            events.append(event("same_version_no_package", port=port))
                            continue
                        connection.settimeout(5)
                        try:
                            with context.wrap_socket(connection, server_side=True) as tls:
                                header = bytearray()
                                while len(header) < 4:
                                    chunk = tls.recv(4 - len(header))
                                    if not chunk:
                                        break
                                    header.extend(chunk)
                                length = int.from_bytes(header[2:4], "big") if len(header) == 4 else None
                                events.append(event(
                                    "pairing_request_observed", port=port,
                                    tls_version=tls.version(), header_hex=header.hex(),
                                    request_type=header[1] if len(header) == 4 else None,
                                    declared_payload_length=length,
                                ))
                                observed_request = len(header) == 4
                                # Close without sending an application packet. In particular,
                                # never send the type-6 success response that would pair.
                        except (OSError, ssl.SSLError) as error:
                            events.append(event("tls_error", port=port,
                                                error_type=type(error).__name__,
                                                error=str(error)[:200]))
                    print(json.dumps(events[-1]), flush=True)
        finally:
            for listener in listeners:
                listener.close()
            args.log.parent.mkdir(parents=True, exist_ok=True)
            args.log.write_text(json.dumps({
                "host_ip": args.host_ip, "target_ip": args.target_ip,
                "seconds": args.seconds, "events": events,
                "application_response_sent": False,
                "software_package_served": False,
            }, indent=2) + "\n")
    print(f"Observed {len(events)} connections", flush=True)


if __name__ == "__main__":
    main()
