#!/usr/bin/env python3
"""Receive one raw Touch 10 backup stream over the isolated direct LAN."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", required=True, help="Remote path being copied")
    parser.add_argument("--expected-bytes", required=True, type=int)
    parser.add_argument("--expected-sha256", help="SHA-256 read on the panel before transfer")
    parser.add_argument("--host-ip", default="10.77.10.1")
    parser.add_argument("--target-ip", default="10.77.10.10")
    parser.add_argument("--port", type=int, default=8878)
    parser.add_argument("--connect-timeout", type=int, default=120)
    args = parser.parse_args()
    if args.expected_bytes <= 0:
        parser.error("--expected-bytes must be positive")
    if args.expected_sha256 and (len(args.expected_sha256) != 64 or
                                 any(c not in "0123456789abcdef" for c in args.expected_sha256)):
        parser.error("--expected-sha256 must be 64 lowercase hex characters")
    output = args.output.resolve()
    partial = output.with_name(output.name + ".partial")
    manifest = output.with_name(output.name + ".json")
    if any(p.exists() for p in (output, partial, manifest)):
        parser.error("output, partial, or manifest already exists")
    if not output.parent.is_dir():
        parser.error("output parent directory must already exist")
    os.umask(0o077)
    record = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "source": args.source, "output": str(output),
              "expected_bytes": args.expected_bytes,
              "expected_sha256": args.expected_sha256,
              "target_ip": args.target_ip, "complete": False}
    digest = hashlib.sha256()
    total = 0
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((args.host_ip, args.port))
            listener.listen(1)
            deadline = time.monotonic() + args.connect_timeout
            print(f"ready for {args.source} from {args.target_ip} on {args.host_ip}:{args.port}", flush=True)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("source did not connect")
                listener.settimeout(min(remaining, 5))
                try:
                    connection, peer = listener.accept()
                except TimeoutError:
                    continue
                if peer[0] == args.target_ip:
                    break
                connection.close()
            with connection, partial.open("xb") as destination:
                connection.settimeout(30)
                print(f"receiving from {peer[0]}", flush=True)
                while True:
                    chunk = connection.recv(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > args.expected_bytes:
                        raise ValueError(f"received more than {args.expected_bytes} bytes")
                    destination.write(chunk)
                    digest.update(chunk)
                    if total and total % (64 * 1024 * 1024) < len(chunk):
                        print(f"received {total}/{args.expected_bytes} bytes", flush=True)
        record["received_bytes"] = total
        record["sha256"] = digest.hexdigest()
        if total != args.expected_bytes:
            raise ValueError(f"received {total}, expected {args.expected_bytes} bytes")
        if args.expected_sha256 and record["sha256"] != args.expected_sha256:
            raise ValueError("received SHA-256 differs from panel's pre-transfer hash")
        partial.rename(output)
        record["complete"] = True
        print(f"complete: {total} bytes, sha256 {record['sha256']}", flush=True)
    except Exception as error:
        record["received_bytes"] = total
        record["sha256"] = digest.hexdigest()
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest.write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
