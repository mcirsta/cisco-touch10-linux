#!/usr/bin/env python3
"""Bounded, read-only capture of the stock Touch 10 input event stream."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess


EVENT = struct.Struct("<IIHHi")  # Linux ARM32 input_event: timeval, type, code, value
CODE_NAMES = {
    (0, 0): "SYN_REPORT",
    (3, 0x30): "ABS_MT_TOUCH_MAJOR",
    (3, 0x35): "ABS_MT_POSITION_X",
    (3, 0x36): "ABS_MT_POSITION_Y",
    (3, 0x39): "ABS_MT_TRACKING_ID",
    (3, 0x3a): "ABS_MT_PRESSURE",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120:
        parser.error("--seconds must be between 1 and 120")
    args.output.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc).isoformat()
    # Bound the reader on the panel itself. Closing SSH alone leaves a cat
    # blocked in read(), so the remote shell must kill its exact child.
    remote = (
        "bash -c 'cat /dev/input/event1 & reader=$!; "
        "trap \"kill $reader 2>/dev/null\" EXIT HUP INT TERM; "
        f"sleep {args.seconds}; exit 0'"
    )
    command = [
        "ssh", "-T", "-F", "/home/marius/ext_proj/touch10/access/ssh_config",
        "touch10", remote,
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        raw, stderr = process.communicate(timeout=args.seconds + 10)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        try:
            raw, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            raw, stderr = process.communicate()

    (args.output / "event1.raw").write_bytes(raw)
    (args.output / "ssh.stderr").write_bytes(stderr)
    events = []
    for offset in range(0, len(raw) - len(raw) % EVENT.size, EVENT.size):
        sec, usec, kind, code, value = EVENT.unpack_from(raw, offset)
        events.append({
            "time": f"{sec}.{usec:06d}", "type": kind, "code": code,
            "name": CODE_NAMES.get((kind, code), ""), "value": value,
        })
    record = {
        "started_utc": started,
        "duration_limit_seconds": args.seconds,
        "read_only_device_command": "cat /dev/input/event1",
        "host_timeout_unexpected": timed_out,
        "ssh_exit_code": process.returncode,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "event_count": len(events),
        "trailing_bytes": len(raw) % EVENT.size,
        "events": events,
    }
    (args.output / "events.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Captured {len(events)} events in {len(raw)} bytes: {args.output}")
    return 0 if not timed_out and process.returncode == 0 and len(raw) % EVENT.size == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
