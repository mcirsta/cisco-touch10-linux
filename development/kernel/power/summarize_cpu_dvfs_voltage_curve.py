#!/usr/bin/env python3
"""Bind the three 350 MHz voltage/power points to audited, recovered boots."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POINTS = {
    "0x28": {
        "nominal_uv": 1202740,
        "kernel": "6.18.48-perrier-ram114",
        "power": "development/runs/20261113T170052Z-cpu-dvfs-power/result.json",
    },
    "0x24": {
        "nominal_uv": 1152100,
        "kernel": "6.18.48-perrier-ram116",
        "power": "development/runs/20261113T173500Z-cpu-dvfs-mid-power/result.json",
        "fixed_rate": "development/runs/20261113T173426Z-cpu-dvfs-mid-trial/result.json",
        "image_audit": "development/perrier-ramenv/cpu-dvfs-mid-trial/reviewed-image.json",
        "recovery": "development/runs/20261113T173319Z-uboot-ram116-a247ae/result.json",
        "postflight_cleanup": "development/runs/20261113T174033Z-p14-ram116-cleanup/result.json",
    },
    "0x20": {
        "nominal_uv": 1101460,
        "kernel": "6.18.48-perrier-ram115",
        "power": "development/runs/20261113T171730Z-cpu-dvfs-low-power/result.json",
        "validation": "development/kernel/validation-cpu-dvfs-low-trial.json",
    },
}
CURVE_OUT = ROOT / "development/kernel/validation-cpu-dvfs-voltage-curve.json"
MID_OUT = ROOT / "development/kernel/validation-cpu-dvfs-mid-trial.json"
FACTORY_P8 = "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad"


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text())


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    measurements = {}
    for selector, point in POINTS.items():
        result = read(point["power"])
        assert result["passed"] and result["summary"]["sample_count"] == 96
        rail = result["summary"]["rail_power_mw"]
        measurements[selector] = {
            "nominal_uv": point["nominal_uv"], "kernel": point["kernel"],
            "peak_cpu_millicelsius": result["summary"]["peak_cpu_millicelsius"],
            "idle_likely_mpu_mw": rail["idle"]["3-0041:channel1"]["350"]["mean"],
            "load_likely_mpu_mw": rail["load"]["3-0041:channel1"]["350"]["mean"],
            "idle_5v_channel_mw": rail["idle"]["3-0040:channel3"]["350"]["mean"],
            "load_5v_channel_mw": rail["load"]["3-0040:channel3"]["350"]["mean"],
        }
    mid = POINTS["0x24"]
    fixed = read(mid["fixed_rate"])
    audit = read(mid["image_audit"])
    recovery = read(mid["recovery"])
    cleanup = read(mid["postflight_cleanup"])
    low_validation = read(POINTS["0x20"]["validation"])
    assert fixed["passed"] and audit["passed"] and low_validation["status"] == "passed_bounded_ram_test"
    assert ([fixed["stages"][name]["regulator"] for name in
             ("before", "low_idle", "low_load", "restored")] ==
            [1215400, 1152100, 1152100, 1215400])
    assert recovery["status"] == "passed" and recovery["stock_recovered"]
    assert recovery["stock_p8_sha256"] == FACTORY_P8 and recovery["adc_postflight"]["passed"]
    assert recovery["after"]["factory_app"] == "running"
    assert cleanup["passed"] and cleanup["stock_environment_sha256"] == FACTORY_P8
    assert cleanup["stock_boot_id"] == recovery["after"]["boot_id"]
    for mode in ("idle", "load"):
        for key in ("likely_mpu_mw", "5v_channel_mw"):
            values = [measurements[s][mode + "_" + key] for s in ("0x28", "0x24", "0x20")]
            assert values[0] > values[1] > values[2], (mode, key, values)
    reduction = {}
    for selector in ("0x24", "0x20"):
        reduction[selector] = {}
        for mode in ("idle", "load"):
            reduction[selector][mode] = {}
            for key in ("likely_mpu_mw", "5v_channel_mw"):
                baseline = measurements["0x28"][mode + "_" + key]
                candidate = measurements[selector][mode + "_" + key]
                delta = baseline - candidate
                reduction[selector][mode][key] = {
                    "delta_mw": round(delta, 2),
                    "percent": round(delta * 100 / baseline, 2),
                    "equivalent_joules_per_300_seconds": round(delta * 0.3, 2),
                }
    mid_record = {
        "validated_at": now, "status": "passed_bounded_ram_test",
        "profile": "cpu-dvfs-mid-trial", "kernel": mid["kernel"],
        "scope": "350 MHz/1.1521 V intermediate OPP, 700 MHz/1.2154 V unchanged; 20-second two-core test, 96 guarded power samples and watchdog stock recovery",
        "observations": {
            "fixed_rate_measured_drop_mv": fixed["low_voltage_drop_mv"],
            "fixed_load_sampled_cpu_millicelsius": fixed["stages"]["low_load"]["thermal"],
            "power": measurements["0x24"],
            "reduction_vs_0x28": reduction["0x24"],
            "factory_p8_sha256": FACTORY_P8,
            "stock_recovered": True,
            "adc_postflight_passed": True,
        },
        "limits": [
            "The 1.1521 V point had a 20-second loaded transition and power phases, not a five-minute hold.",
            "INA channels are identified from stock software and load response, without PCB net confirmation.",
            "The 5 V channel is not verified whole-device input and must not be summed with nested rails.",
            "Power points were measured in separate RAM boots; ambient and workload variation remain.",
        ],
        "evidence": {k: mid[k] for k in ("image_audit", "fixed_rate", "power", "recovery", "postflight_cleanup")},
    }
    curve_record = {
        "validated_at": now, "status": "measured_three_point_ram_curve",
        "fixed_cpu_mhz": 350,
        "conditions": "Both CPUs online, one-second INA sampling in repeated idle and two-core load phases, 24 samples per frequency/mode/image; display not cycled",
        "points": measurements, "reduction_vs_0x28": reduction,
        "interpretation": "Monitored likely MPU-rail and 5 V-channel power decreased monotonically at lower 350 MHz selectors. Equal-duration joule equivalents are calculated from mean-power differences, not direct energy integration or fixed-workload energy.",
        "limits": [
            "The rail mapping is from stock software and load response, not PCB net tracing.",
            "The monitored 5 V channel is not proven to be whole-device input; rails may be nested.",
            "Separate boots can differ in ambient temperature, startup state and CPU worker scheduling.",
            "Only selector 0x20 had a five-minute two-core hold and paired schedutil sample; neither point has overnight or error-checked compute qualification.",
            "The factory boot image and canonical CPU policy have not been changed.",
        ],
        "evidence": {selector: {key: value for key, value in point.items()
                                 if key in ("power", "fixed_rate", "image_audit", "recovery", "postflight_cleanup", "validation")}
                     for selector, point in POINTS.items()},
    }
    MID_OUT.write_text(json.dumps(mid_record, indent=2) + "\n")
    CURVE_OUT.write_text(json.dumps(curve_record, indent=2) + "\n")
    print(json.dumps({"mid_record": str(MID_OUT), "curve_record": str(CURVE_OUT),
                      "points": measurements, "reduction_vs_0x28": reduction}, indent=2))


if __name__ == "__main__":
    main()
