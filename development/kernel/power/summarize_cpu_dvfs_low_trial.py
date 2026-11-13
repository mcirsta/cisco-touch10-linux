#!/usr/bin/env python3
"""Bind the ram115 voltage/power observations to their recovered RAM boots."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "development/kernel/validation-cpu-dvfs-low-trial.json"

PATHS = {
    "image_audit": "development/perrier-ramenv/cpu-dvfs-low-trial/reviewed-image.json",
    "baseline_validation": "development/kernel/validation-cpu-dvfs-trial.json",
    "short_low_probe": "development/runs/20261113T170316Z-mpu-low-selectors/result.json",
    "baseline_power": "development/runs/20261113T170052Z-cpu-dvfs-power/result.json",
    "fixed_rate_test": "development/runs/20261113T171335Z-cpu-dvfs-low-trial/result.json",
    "low_power": "development/runs/20261113T171730Z-cpu-dvfs-low-power/result.json",
    "extended_load": "development/runs/20261113T171954Z-cpu-dvfs-low-endurance/result.json",
    "hardware_clock_sampler": "development/runs/20261113T172509Z-cpu-dvfs-low-sampler/result.json",
    "first_recovery": "development/runs/20261113T171227Z-uboot-ram115-86a4a6/result.json",
    "second_recovery": "development/runs/20261113T171624Z-uboot-ram115-ba3e74/result.json",
}


def round2(value: float) -> float:
    return round(value, 2)


def main() -> None:
    data = {name: json.loads((ROOT / path).read_text()) for name, path in PATHS.items()}
    assert data["image_audit"]["passed"] and data["image_audit"]["kernel"] == "6.18.48-perrier-ram115"
    assert data["baseline_validation"]["status"] == "passed_bounded_ram_test"
    for name in ("short_low_probe", "baseline_power", "fixed_rate_test", "low_power",
                 "extended_load", "hardware_clock_sampler"):
        assert data[name]["passed"], name
    for name in ("first_recovery", "second_recovery"):
        result = data[name]
        assert result["status"] == "passed" and result["stock_recovered"]
        assert result["stock_p8_sha256"] == "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad"
        assert result["adc_postflight"]["passed"]
    fixed = data["fixed_rate_test"]["stages"]
    assert [fixed[x]["freq"] for x in ("before", "low_idle", "low_load", "restored")] == \
        [700000, 350000, 350000, 700000]
    assert [fixed[x]["regulator"] for x in ("before", "low_idle", "low_load", "restored")] == \
        [1215400, 1101460, 1101460, 1215400]
    endurance = data["extended_load"]["summary"]
    assert endurance["seconds"] == 300 and endurance["sample_count"] == 31
    power = data["low_power"]["summary"]
    baseline = data["baseline_power"]["summary"]
    assert power["sample_count"] == baseline["sample_count"] == 96
    comparison = {}
    for mode in ("idle", "load"):
        comparison[mode] = {}
        for rail in ("3-0041:channel1", "3-0040:channel3"):
            old = baseline["rail_power_mw"][mode][rail]["350"]["mean"]
            new = power["rail_power_mw"][mode][rail]["350"]["mean"]
            high = power["rail_power_mw"][mode][rail]["700"]["mean"]
            comparison[mode][rail] = {
                "350mhz_1p20274v_mw": old,
                "350mhz_1p10146v_mw": new,
                "cross_boot_reduction_mw": round2(old - new),
                "cross_boot_reduction_percent": round2((old - new) * 100 / old),
                "five_minute_equivalent_joules_saved": round2((old - new) * 300 / 1000),
                "same_boot_700mhz_1p2154v_mw": high,
                "same_boot_700_minus_350_mw": round2(high - new),
            }
    sampler = data["hardware_clock_sampler"]["summary"]
    assert all(phase["stable_low_at_700_samples"] == 0 for phase in sampler.values())
    low_count = lambda phase: sum(p["count"] for p in sampler[phase]["pairs"]
                                  if (p["policy_khz"], p["hardware_khz"],
                                      p["regulator_uv"], p["vc_before"], p["vc_after"]) ==
                                     (350000, 350000, 1101460, 32, 32))
    record = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed_bounded_ram_test",
        "profile": "cpu-dvfs-low-trial",
        "kernel": "6.18.48-perrier-ram115",
        "scope": "Mainline cpufreq-dt/OPP with Perrier VC bypass at 350 MHz/1.10146 V and 700 MHz/1.2154 V; two CPUs online; U-Boot RAM boot, watchdog recovery, no display cycling",
        "observations": {
            "short_350mhz_low_voltage_probe_selectors": ["0x24", "0x20"],
            "fixed_frequency_mhz": [700, 350, 700],
            "fixed_selector_hex": ["29", "20", "29"],
            "fixed_regulator_nominal_microvolts": [1215400, 1101460, 1215400],
            "fixed_low_measured_ina_millivolts": fixed["low_idle"]["ina1"][0],
            "fixed_350mhz_two_core_load_seconds": 20,
            "fixed_load_sampled_cpu_temperature_millicelsius": fixed["low_load"]["thermal"],
            "extended_350mhz_two_core_load_seconds": 300,
            "extended_load_samples": endurance["sample_count"],
            "extended_load_peak_cpu_temperature_millicelsius": endurance["peak_cpu_millicelsius"],
            "extended_load_likely_mpu_millivolts_range": endurance["likely_mpu_voltage_millivolts"],
            "extended_load_likely_mpu_milliamps_range": endurance["likely_mpu_current_milliamps"],
            "power_sample_count_per_image": 96,
            "power_peak_cpu_temperature_millicelsius": power["peak_cpu_millicelsius"],
            "350mhz_voltage_power_comparison": comparison,
            "schedutil_idle_before_stable_low_samples": low_count("idle_before"),
            "schedutil_idle_after_stable_low_samples": low_count("idle_after"),
            "schedutil_loaded_stable_high_samples": next(p["count"] for p in sampler["load"]["pairs"]
                                                     if p["hardware_khz"] == 700000 and p["vc_before"] == p["vc_after"] == 41),
            "schedutil_samples_per_phase": 200,
            "hardware_700_mhz_with_stable_low_vc_selector_samples": 0,
            "both_ram_sessions_stock_recovered": True,
            "factory_p8_sha256": "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad",
            "adc_postflight_passed_both_sessions": True,
        },
        "interpretation": "The low selector reduced monitored MPU-rail power by about 22% at the same 350 MHz point in separate guarded runs. The 5 V monitor fell by about 1.2-1.3%. Fixed-duration joule equivalents are calculated from mean power, not direct energy integration. The paired dynamic sampler found no stable low VC selector around a 700 MHz hardware-clock read.",
        "limits": [
            "INA channel 3-0041:1 is a likely MPU rail from stock software and load response, without PCB net confirmation.",
            "The 3-0040:3 5 V channel is not verified as whole-device input; rails may be nested and must not be summed.",
            "Cross-boot power differences include ambient, temperature, workload scheduling and measurement uncertainty.",
            "Five minutes of loaded operation does not establish overnight or worst-case temperature stability.",
            "Sequential sysfs fields can straddle a frequency/voltage transition; the sampler brackets the hardware clock with VC reads.",
            "CPU hotplug, generic OMAP PM/AVS, persistent installation and full thermal cooling remain unqualified.",
        ],
        "evidence": PATHS,
    }
    OUT.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"record": str(OUT), "status": record["status"],
                      "comparison": comparison}, indent=2))


if __name__ == "__main__":
    main()
