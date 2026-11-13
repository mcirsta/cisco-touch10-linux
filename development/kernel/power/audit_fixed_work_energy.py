#!/usr/bin/env python3
"""Audit the bounded, deterministic ARM RAM benchmark and native reference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "perrier_fixed_work_energy.c"
ARM = HERE / "perrier_fixed_work_energy.arm"
NATIVE = HERE / "perrier_fixed_work_energy.native"
REVIEW = HERE / "perrier-fixed-work-energy-review.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = SOURCE.read_text()
    assert 'const uint32_t seeds[2] = { 0x12345678u, 0x9e3779b9u }' in source
    assert 'pthread_setaffinity_np' in source and 'CPU_SET(w->cpu' in source
    assert 'atomic_load_explicit(&done' in source
    assert 'temperature >= 75000' in source
    assert 'MAX_SAMPLES 1000u' in source and 'SAMPLE_NS 200000000L' in source
    assert 'strcmp(name, "perrier-vdd-mpu")' in source
    assert '3-0041/hwmon/hwmon*/in1_input' in source
    assert '3-0040/hwmon/hwmon*/in3_input' in source
    assert 'O_RDONLY | O_CLOEXEC' in source
    no_comments = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    assert not re.search(r'\b(O_RDWR|O_WRONLY|PROT_WRITE|MAP_SHARED)\b', no_comments)
    assert not re.search(r'\b(ioctl|pwrite|writel|system|execve)\s*\(', no_comments)
    assert ARM.stat().st_size < 180000 and NATIVE.stat().st_size < 180000
    native = subprocess.run([str(NATIVE), 'ref', '100000'], capture_output=True,
                            text=True, check=True, timeout=10)
    arm = subprocess.run(['qemu-arm', '-cpu', 'cortex-a9', str(ARM), 'ref', '100000'],
                         capture_output=True, text=True, check=True, timeout=10)
    assert native.stdout == arm.stdout == 'REF 100000 46f5ec59 bb10fc4c\n'
    review = {
        'passed': True, 'device_run': False,
        'source_sha256': sha(SOURCE), 'arm_sha256': sha(ARM),
        'native_sha256': sha(NATIVE), 'arm_bytes': ARM.stat().st_size,
        'read_only_sensors': True, 'two_pinned_workers': True,
        'temperature_abort_millicelsius': 75000,
        'maximum_sample_count': 1000, 'sample_interval_ms': 200,
        'cross_architecture_reference': native.stdout.strip(),
    }
    REVIEW.write_text(json.dumps(review, indent=2) + '\n')
    print(json.dumps(review, indent=2))


if __name__ == '__main__':
    main()
