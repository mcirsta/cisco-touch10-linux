#!/usr/bin/env python3
"""Pin the small RAM-only MPU voltage-controller transport experiment."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "omap4_mpu_bypass_step.c"
BINARY = HERE / "omap4_mpu_bypass_step.arm"
REVIEW = HERE / "omap4-mpu-bypass-step-review.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = SOURCE.read_text()
    assert '#define PRM_BASE 0x4a306000u' in source
    assert '#define PRM_SIZE 8192u' in source
    assert '#define VC_VALID (1u << 24)' in source
    assert '#define VC_ACK (1u << 14)' in source
    assert '#define VC_ERRORS (7u << 11)' in source
    assert '#define VC_COMMAND(vsel) (((uint32_t)(vsel) << 16) | (0x55u << 8) | 0x12u)' in source
    assert 'strcmp(name.release, "6.18.48-perrier-ram113")' in source
    assert 'perrier-interactive-ram113' in source
    assert 'read_number("/sys/class/thermal/thermal_zone0/temp") >= 70000' not in source
    assert 'temp < 0 || temp >= 70000' in source
    assert 'PROT_READ | PROT_WRITE' in source and 'O_RDWR | O_SYNC' in source
    assert 'put(0x10u, VC_STATUS);' in source
    assert 'put(0x1ba0u, value);' in source
    assert 'put(0x1ba0u, value | VC_VALID);' in source
    assert '!(word(0x1ba0u) & VC_VALID)' in source
    assert '(status & VC_STATUS) == VC_ACK' in source
    assert source.count('command(0x29u)') == 2
    assert source.count('command(0x28u)') == 1
    assert 'if (!(word(0x1ba0u) & VC_VALID))' in source
    assert 'clock == 700000' in source and 'voltage >= 1150' in source
    assert 'if (!safe_runtime())' in source and 'if (!expected_prm()' in source
    no_comments = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    assert not re.search(r'\b(system|execve|pwrite|ioctl|fork|pthread_create)\s*\(', no_comments)
    assert BINARY.stat().st_size < 131072
    qemu = subprocess.run(
        ["qemu-arm", "-cpu", "cortex-a9", "-strace", str(BINARY)],
        capture_output=True, text=True, timeout=5,
    )
    assert qemu.returncode == 2
    assert "RAM runtime preflight failed" in qemu.stderr
    assert 'open("/dev/mem"' not in qemu.stderr
    review = {
        "passed": True,
        "device_run": False,
        "source_sha256": sha(SOURCE),
        "binary_sha256": sha(BINARY),
        "binary_size": BINARY.stat().st_size,
        "kernel": "6.18.48-perrier-ram113",
        "scope": "same selector 0x29, one step to 0x28, restore 0x29",
        "max_low_voltage_dwell_seconds": 0.6,
        "prm_mapping": "0x4a306000..0x4a307fff",
        "only_voltage_target": "TWL6032 slave 0x12 register 0x55",
        "qemu_denied_before_mmio": True,
    }
    REVIEW.write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps(review, indent=2))


if __name__ == "__main__":
    main()
