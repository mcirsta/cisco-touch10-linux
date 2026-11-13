#!/usr/bin/env python3
"""Audit the read-only, low-overhead ram114 DVFS observation helper."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "omap4_dvfs_sampler.c"
BINARY = HERE / "omap4_dvfs_sampler.arm"
REVIEW = HERE / "omap4-dvfs-sampler-review.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = SOURCE.read_text()
    assert '#define PRM_BASE 0x4a306000u' in source
    assert '#define PRM_SIZE 8192u' in source
    assert '#define COUNT 200' in source
    assert 'next.tv_nsec += 100000000;' in source
    assert 'strcmp(name.release, "6.18.48-perrier-ram114")' in source
    assert 'O_RDONLY | O_SYNC | O_CLOEXEC' in source
    assert 'mmap(NULL, PRM_SIZE, PROT_READ, MAP_SHARED' in source
    assert 'prm[0x1ba0u / 4u]' in source and 'prm[0x10u / 4u]' in source
    assert 'policy0/cpuinfo_cur_freq' in source
    assert 'uint32_t before = prm[0x1ba0u / 4u]' in source
    assert 'uint32_t after = prm[0x1ba0u / 4u]' in source
    no_comments = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    assert not re.search(r'\b(O_RDWR|O_WRONLY|PROT_WRITE)\b', no_comments)
    assert not re.search(r'\b(ioctl|pwrite|writel|memcpy|fork|system|execve)\s*\(', no_comments)
    assert BINARY.stat().st_size < 131072
    qemu = subprocess.run(["qemu-arm", "-cpu", "cortex-a9", "-strace", str(BINARY)],
                          capture_output=True, text=True, timeout=5)
    assert qemu.returncode == 2 and "ram114 schedutil preflight failed" in qemu.stderr
    assert 'open("/dev/mem"' not in qemu.stderr
    review = {"passed": True, "device_run": False,
              "source_sha256": sha(SOURCE), "binary_sha256": sha(BINARY),
              "binary_size": BINARY.stat().st_size,
              "read_only_mmio": True, "sample_count": 200,
              "sample_period_ms": 100, "kernel": "6.18.48-perrier-ram114"}
    REVIEW.write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps(review, indent=2))


if __name__ == "__main__":
    main()
