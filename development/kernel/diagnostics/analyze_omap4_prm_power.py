#!/usr/bin/env python3
"""Decode a fixed OMAP4460 PRM snapshot without touching the device."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_omap4_prm_power_read import EXPECTED

BASE = 0x4a307000
MAINLINE_ON_UV = 1_375_000
MAINLINE_ONLP_UV = 1_375_000
MAINLINE_RET_UV = 837_500
MAINLINE_VP_MAX_UV = {"mpu": 1_410_000, "iva": 1_260_000, "core": 1_200_000}


def selector_uv(value: int) -> int | None:
    if value == 0:
        return None
    if value == 0x3a:
        return 1_350_000
    if not 1 <= value <= 0x39:
        return None
    # Stock TWL6032 EPROM offset 0x5b has bit 3 set.
    return 709_000 + (value - 1) * 12_660


def selector_for_uv(value: int) -> int:
    if value == 0:
        return 0
    if not 709_000 <= value <= selector_uv(0x39):
        raise ValueError(f"outside the ordinary TWL6032 selector range: {value}")
    return (value - 709_000 + 12_659) // 12_660 + 1


def byte(value: int, index: int) -> int:
    return (value >> (8 * index)) & 0xff


def decode(path: Path) -> dict:
    lines = path.read_text().splitlines()
    if len(lines) != len(EXPECTED):
        raise ValueError(f"expected {len(EXPECTED)} register lines, found {len(lines)}")
    raw = {}
    for line, (name, offset) in zip(lines, EXPECTED):
        fields = line.split(",")
        if len(fields) != 3 or fields[0] != name or int(fields[1], 16) != BASE + offset:
            raise ValueError(f"unexpected register line: {line!r}")
        value = int(fields[2], 16)
        if not 0 <= value <= 0xffffffff:
            raise ValueError(f"invalid register word: {line!r}")
        raw[name] = value
    domains = {}
    mainline_command = ((selector_for_uv(MAINLINE_ON_UV) << 24) |
                        (selector_for_uv(MAINLINE_ONLP_UV) << 16) |
                        (selector_for_uv(MAINLINE_RET_UV) << 8))
    for domain, ra_index in (("core", 0), ("iva", 1), ("mpu", 2)):
        command = raw[f"vc_{domain}_command"]
        vp_config = raw[f"vp_{domain}_config"]
        vp_limit = raw[f"vp_{domain}_vlimitto"]
        current = byte(raw[f"vp_{domain}_voltage"], 0)
        on, onlp, ret, off = [byte(command, index) for index in (3, 2, 1, 0)]
        domains[domain] = {
            "vc_slave_address": byte(raw["vc_smps_sa"], ra_index) & 0x7f,
            "vc_voltage_register": byte(raw["vc_smps_ra_vol"], ra_index),
            "vc_command_register": byte(raw["vc_smps_ra_cmd"], ra_index),
            "vc_command_selectors": {"on": on, "onlp": onlp, "ret": ret, "off": off},
            "vc_command_uv": {key: selector_uv(value) for key, value in
                              (("on", on), ("onlp", onlp), ("ret", ret), ("off", off))},
            "vp_enabled": bool(vp_config & 1),
            "vp_timeout_enabled": bool(vp_config & 8),
            "vp_init_selector": byte(vp_config, 1),
            "vp_current_selector": current,
            "vp_current_request_uv": selector_uv(current),
            "vp_limit_min_selector": byte(vp_limit, 2),
            "vp_limit_max_selector": byte(vp_limit, 3),
            "vp_limit_timeout_cycles": vp_limit & 0xffff,
            "pristine_mainline_command": f"0x{mainline_command:08x}",
            "stock_command_matches_pristine_mainline": command == mainline_command,
            "pristine_mainline_on_exceeds_domain_vp_max":
                MAINLINE_ON_UV > MAINLINE_VP_MAX_UV[domain],
            "pristine_mainline_vp_init_would_clear_enabled_bit": bool(vp_config & 1),
        }
    expected_map = {
        "mpu": (0x12, 0x55, 0x56),
        "core": (0x12, 0x5b, 0x5c),
        "iva": (0x12, 0x49, 0x4a),
    }
    mapping_match = all((item["vc_slave_address"], item["vc_voltage_register"],
                         item["vc_command_register"]) == expected_map[name]
                        for name, item in domains.items())
    return {
        "source": str(path),
        "register_count": len(raw),
        "twl6032_offset_bit_assumed_from_prior_read": True,
        "domains": domains,
        "expected_cisco_twl6032_address_map_matches": mapping_match,
        "pristine_mainline_on_target_uv": MAINLINE_ON_UV,
        "pristine_mainline_command": f"0x{mainline_command:08x}",
        "stock_mpu_command_differs_from_generic_mainline_1375mv":
            domains["mpu"]["vc_command_selectors"]["on"] !=
            selector_for_uv(MAINLINE_ON_UV),
        "raw": {name: f"0x{value:08x}" for name, value in raw.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = decode(args.input)
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
