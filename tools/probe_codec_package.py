#!/usr/bin/env python3
"""Read a codec's Touch software announcement on TCP 4045.

This only connects and reads. It never pairs a Touch 10 or fetches a package.
The field format comes from the older Touch 10 swsync client, so a newer codec
may announce software differently.
"""

import argparse
import json
import socket
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codec_ip", help="IPv4 or IPv6 address of the codec")
    parser.add_argument("--port", type=int, default=4045)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 0 < args.timeout <= 30:
        parser.error("port must be 1..65535 and timeout must be 0..30 seconds")

    try:
        with socket.create_connection((args.codec_ip, args.port), args.timeout) as sock:
            sock.settimeout(args.timeout)
            chunks = []
            size = 0
            while size < 4096:
                chunk = sock.recv(min(1024, 4096 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
    except (OSError, TimeoutError) as exc:
        print(f"TCP {args.port} read failed: {exc}", file=sys.stderr)
        return 1

    raw = b"".join(chunks)
    fields = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"version", "method", "url", "targets"}:
            fields[key.strip()] = value.strip()
    print(json.dumps({"codec_ip": args.codec_ip, "port": args.port,
                      "fields": fields, "raw": raw.decode("utf-8", "replace"),
                      "truncated": len(raw) == 4096}, indent=2))
    return 0 if raw else 2


if __name__ == "__main__":
    raise SystemExit(main())
