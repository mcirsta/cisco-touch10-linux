#!/usr/bin/env python3
"""Audit the bounded, read-only PRM snapshot helper entirely off-device."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "omap4_prm_power_read.c"
BINARY = HERE / "omap4_prm_power_read.arm"
REVIEW = HERE / "omap4-prm-power-read-review.json"

# OMAP4460 TRM SWPU235AB, DEVICE_PRM offsets, all within 0x4a307000.
EXPECTED = [
    ("voltctrl", 0xb10),
    ("voltsetup_core_off", 0xb28),
    ("voltsetup_mpu_off", 0xb2c),
    ("voltsetup_iva_off", 0xb30),
    ("voltsetup_core_ret_sleep", 0xb34),
    ("voltsetup_mpu_ret_sleep", 0xb38),
    ("voltsetup_iva_ret_sleep", 0xb3c),
    ("vp_core_config", 0xb40),
    ("vp_core_vlimitto", 0xb48),
    ("vp_core_voltage", 0xb4c),
    ("vp_core_vstepmax", 0xb50),
    ("vp_core_vstepmin", 0xb54),
    ("vp_mpu_config", 0xb58),
    ("vp_mpu_vlimitto", 0xb60),
    ("vp_mpu_voltage", 0xb64),
    ("vp_mpu_vstepmax", 0xb68),
    ("vp_mpu_vstepmin", 0xb6c),
    ("vp_iva_config", 0xb70),
    ("vp_iva_vlimitto", 0xb78),
    ("vp_iva_voltage", 0xb7c),
    ("vp_iva_vstepmax", 0xb80),
    ("vp_iva_vstepmin", 0xb84),
    ("vc_smps_sa", 0xb88),
    ("vc_smps_ra_vol", 0xb8c),
    ("vc_smps_ra_cmd", 0xb90),
    ("vc_core_command", 0xb94),
    ("vc_mpu_command", 0xb98),
    ("vc_iva_command", 0xb9c),
    ("vc_cfg_channel", 0xba4),
    ("vc_cfg_i2c_mode", 0xba8),
    ("vc_cfg_i2c_clk", 0xbac),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = SOURCE.read_text()
    found = [(name, int(offset, 16)) for name, offset in re.findall(
        r'\{ "([a-z0-9_]+)", 0x([0-9a-f]+)u \}', source)]
    assert found == EXPECTED, "fixed register allowlist changed"
    assert len({offset for _, offset in found}) == len(EXPECTED)
    assert all(0 <= offset <= 0xffc and offset % 4 == 0 for _, offset in found)
    assert '#define PRM_PAGE_BASE 0x4a307000u' in source
    assert '#define PRM_PAGE_SIZE 4096u' in source
    assert 'open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC)' in source
    assert 'mmap(NULL, PRM_PAGE_SIZE, PROT_READ, MAP_SHARED' in source
    assert 'int main(void)' in source and 'argc' not in source and 'argv' not in source
    code = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    assert not re.search(r'\b(O_WRONLY|O_RDWR|PROT_WRITE|MAP_ANONYMOUS|ioctl|pwrite|memcpy)\b', code)
    assert BINARY.stat().st_size < 65536
    qemu = subprocess.run(["qemu-arm", "-cpu", "cortex-a9", "-strace", str(BINARY)],
                          capture_output=True, text=True, timeout=5)
    assert qemu.returncode == 1
    assert 'open("/dev/mem",O_RDONLY' in qemu.stderr
    assert 'No such file or directory' in qemu.stderr
    assert 'mmap(' not in qemu.stderr
    report = {
        "passed": True,
        "device_run": False,
        "source_sha256": sha256(SOURCE),
        "binary_sha256": sha256(BINARY),
        "binary_sha512": hashlib.sha512(BINARY.read_bytes()).hexdigest(),
        "binary_size": BINARY.stat().st_size,
        "register_count": len(EXPECTED),
        "page_base": "0x4a307000",
        "highest_offset": f"0x{max(offset for _, offset in EXPECTED):03x}",
        "read_only_open_and_mapping": True,
        "qemu_no_device_open_was_read_only": True,
        "device_writes": False,
    }
    REVIEW.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
