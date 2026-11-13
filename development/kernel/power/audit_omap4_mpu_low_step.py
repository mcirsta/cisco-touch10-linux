#!/usr/bin/env python3
"""Audit the two fixed, reversible 350 MHz VC-bypass probe binaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "omap4_mpu_low_step.c"
REVIEW = HERE / "omap4-mpu-low-step-review.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = SOURCE.read_text()
    assert '#define PRM_BASE 0x4a306000u' in source
    assert '#define PRM_SIZE 8192u' in source
    assert '#if TARGET_SELECTOR != 0x24 && TARGET_SELECTOR != 0x20' in source
    assert 'strcmp(name.release, "6.18.48-perrier-ram114")' in source
    assert 'perrier-interactive-ram114' in source
    assert 'policy0/cpuinfo_cur_freq' in source and 'clock != 350000' in source
    assert 'scaling_governor", "userspace"' in source
    assert 'word(0x1ba0u) == VC_COMMAND(0x28u)' in source
    assert 'VC_COMMAND(selector)' in source and 'command(0x28u)' in source
    assert 'settle = { 2, 0 }' in source
    assert 'TARGET_UV / 1000 - 35' in source
    assert 'restore_ok = command(0x28u)' in source
    assert 'O_RDWR | O_SYNC | O_CLOEXEC' in source
    assert 'PROT_READ | PROT_WRITE' in source
    no_comments = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    calls = re.findall(r'\bput\((0x[0-9a-f]+u),', no_comments)
    assert set(calls) == {'0x10u', '0x1ba0u'} and len(calls) == 3
    assert not re.search(r'\b(ioctl|pwrite|system|execve)\s*\(', no_comments)
    binaries = {}
    for selector in (0x24, 0x20):
        path = HERE / f"omap4_mpu_low_step_{selector:02x}.arm"
        assert path.stat().st_size < 131072
        qemu = subprocess.run(["qemu-arm", "-cpu", "cortex-a9", "-strace", str(path)],
                              capture_output=True, text=True, timeout=5)
        assert qemu.returncode == 2 and "RAM runtime preflight failed" in qemu.stderr
        assert 'open("/dev/mem"' not in qemu.stderr
        binaries[f"0x{selector:02x}"] = {"sha256": sha(path), "size": path.stat().st_size,
                                       "nominal_microvolts": 709000 + (selector - 1) * 12660}
    review = {"passed": True, "device_run": False,
              "source_sha256": sha(SOURCE), "kernel": "6.18.48-perrier-ram114",
              "initial_selector": "0x28", "restore_selector": "0x28",
              "fixed_frequency_khz": 350000, "low_dwell_seconds": 2,
              "binaries": binaries, "persistent_storage_write": False}
    REVIEW.write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps(review, indent=2))


if __name__ == "__main__":
    main()
