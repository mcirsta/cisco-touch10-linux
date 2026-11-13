#!/usr/bin/env python3
"""Check a pinned handoff-address poll image or capture one authorized upload.

``--check`` compiles and validates locally only. ``--run`` starts passive
serial capture before the one-hour wait for a fresh, pinned Touch 10 ROM USB
enumeration. The uploaded image uses a read-only speedup poll, never a write.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

import rom_speedup_poll_probe as capture


SOURCE = capture.ROOT / "tools/rom_speedup_poll_probe.c"
RUNS = capture.ROOT / "evidence/bootrom-handoff-poll-2026-11-08/runs"


def build_binary(folder: Path) -> Path:
    binary = folder / "rom_handoff_poll_probe"
    command = [
        "cc", "-std=c11", "-D_DEFAULT_SOURCE", "-DHANDOFF_POLL", "-O2",
        "-Wall", "-Wextra", "-Werror", str(SOURCE), "-o", str(binary),
        "-lcrypto",
    ]
    subprocess.run(command, cwd=capture.ROOT, check=True)
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", choices=("clear", "set"),
                      help="verify one image entirely offline")
    mode.add_argument("--run", choices=("clear", "set"),
                      help="capture and upload one image on the next cold boot")
    args = parser.parse_args()
    variant = args.check or args.run
    with tempfile.TemporaryDirectory(prefix="touch10-rom-handoff-build-") as temp:
        binary = build_binary(Path(temp))
        subprocess.run([str(binary), "--check", variant], cwd=capture.ROOT,
                       check=True)
        if args.run:
            capture.RUNS = RUNS
            return capture.run_live(binary, variant)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Probe aborted: {exc}", file=sys.stderr)
        raise SystemExit(1)
