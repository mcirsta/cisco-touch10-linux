#!/usr/bin/env python3
"""Measure checksum-verified, fixed-work energy at both CPU OPPs in RAM."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

ARM = HERE / "perrier_fixed_work_energy.arm"
NATIVE = HERE / "perrier_fixed_work_energy.native"
SOURCE = HERE / "perrier_fixed_work_energy.c"
AUDIT = HERE / "perrier-fixed-work-energy-review.json"
PLAN = HERE / "fixed-work-energy-plan.json"
TEMP = "/tmp/perrier-fixed-work-energy"
FACTORY_P8 = "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad"
PROFILES = {
    "cpu-dvfs-trial": ("ram114", 1202740),
    "cpu-dvfs-mid-trial": ("ram116", 1152100),
    "cpu-dvfs-low-trial": ("ram115", 1101460),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(count: int) -> tuple[str, str]:
    result = subprocess.run([str(NATIVE), "ref", str(count)], capture_output=True,
                            text=True, check=True, timeout=30)
    fields = result.stdout.strip().split()
    assert len(fields) == 4 and fields[:2] == ["REF", str(count)]
    return fields[2], fields[3]


def check_artifacts(profile: str) -> tuple[str, int, dict]:
    review = json.loads(AUDIT.read_text())
    assert review["passed"] and review["source_sha256"] == sha(SOURCE)
    assert review["arm_sha256"] == sha(ARM) and review["native_sha256"] == sha(NATIVE)
    version, low_uv = PROFILES[profile]
    image = json.loads((ROOT / "development/perrier-ramenv" /
                        profile / "reviewed-image.json").read_text())
    assert image["passed"] and image["kernel"] == "6.18.48-perrier-" + version
    assert image["dtb_audit"]["opp_hz_uv"] == [[350000000, low_uv], [700000000, 1215400]]
    assert image["watchdog_and_factory_recovery_preserved"]
    return version, low_uv, review


def request_recovery(profile: str) -> None:
    current = json.loads(ram.CURRENT.read_text())
    assert current["status"] in ("interactive", "recovering")
    assert current["profile"] == profile
    target = Path(current["directory"]) / "recover-request.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"mode": "fixed_work_energy_complete"}) + "\n")
    os.replace(temporary, target)


def upload_binary() -> None:
    preflight = ram.remote("set -eu\n"
                           "test \"$(awk '$2 == \"/tmp\" {print $3}' /proc/mounts)\" = tmpfs\n"
                           "test ! -e " + TEMP + "\n")
    preflight.check_returncode()
    data = ARM.read_bytes()
    upload = subprocess.run(ram.SSH + ["umask 077; cat > " + TEMP], input=data,
                            capture_output=True, timeout=30)
    upload.check_returncode()
    readback = subprocess.run(ram.SSH + ["cat " + TEMP], capture_output=True,
                              timeout=30)
    assert readback.returncode == 0 and readback.stdout == data
    chmod = ram.remote("chmod 700 " + TEMP + "\n")
    chmod.check_returncode()


def preflight(version: str) -> None:
    command = f'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-{version}
test "$(uname -r)" = 6.18.48-perrier-{version}
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test "$(cat /sys/block/mmcblk0/ro)" = 1
policy=/sys/devices/system/cpu/cpufreq/policy0
test "$(cat "$policy/scaling_driver")" = cpufreq-dt
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
test "$(cat "$policy/scaling_available_frequencies")" = '350000 700000 '
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 70000
'''
    result = ram.remote(command)
    result.check_returncode()


def single_command(count: int, expected: tuple[str, str], khz: int,
                   uv: int, label: str) -> str:
    assert label.replace("_", "").isalnum() and khz in (350000, 700000)
    assert uv in (1101460, 1152100, 1202740, 1215400)
    return (f'echo "PHASE {label} {khz} {uv}"\n'
            f'{TEMP} run {count} {expected[0]} {expected[1]} {khz} {uv}\n'
            f'echo "END_PHASE {label}"\n')


def control_script(phases: list[tuple[str, int, int]], count: int,
                   expected: tuple[str, str]) -> str:
    text = '''set -eu
policy=/sys/devices/system/cpu/cpufreq/policy0
reg=''
for p in /sys/class/regulator/regulator*; do
    test -r "$p/name" || continue
    test "$(cat "$p/name")" = perrier-vdd-mpu || continue
    test -z "$reg"; reg=$p
done
test -n "$reg"
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
test "$(cat "$reg/microvolts")" = 1215400
restore() {
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
echo userspace > "$policy/scaling_governor"
'''
    for label, khz, uv in phases:
        text += (f'echo {khz} > "$policy/scaling_setspeed"\n'
                 'sleep 3\n'
                 f'test "$(cat "$policy/cpuinfo_cur_freq")" = {khz}\n'
                 f'test "$(cat "$reg/microvolts")" = {uv}\n'
                 'test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 70000\n')
        text += single_command(count, expected, khz, uv, label)
    text += '''echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
test "$(cat "$reg/microvolts")" = 1215400
echo performance > "$policy/scaling_governor"
if dmesg | grep -q 'VC bypass failed'; then exit 5; fi
echo "GUARD $(cat /run/guard.json)"
echo FIXED_WORK_ENERGY_PASS
'''
    return text


def parse_phase(lines: list[str], count: int, expected: tuple[str, str],
                khz: int, uv: int) -> dict:
    samples = []
    result = None
    verified = False
    for line in lines:
        fields = line.split()
        if fields[:1] == ["SAMPLE"]:
            assert len(fields) == 9
            sec = float(fields[1])
            actual_khz, actual_uv, temp, mpu_mv, mpu_ma, five_mv, five_ma = map(int, fields[2:])
            assert actual_khz == khz and actual_uv == uv and temp < 75000
            assert 900 <= mpu_mv <= 1300 and 0 <= mpu_ma <= 2000
            assert 4500 <= five_mv <= 5500 and 0 <= five_ma <= 3000
            samples.append({"seconds": sec, "cpu_millicelsius": temp,
                            "mpu_mw": mpu_mv * mpu_ma / 1000,
                            "five_volt_mw": five_mv * five_ma / 1000})
        elif fields[:1] == ["RESULT"]:
            assert len(fields) == 8 and int(fields[1]) == count
            result = {"duration_ms": int(fields[2]), "worker_hashes": fields[3:5],
                      "worker_ms": [int(fields[5]), int(fields[6])],
                      "sample_count_reported": int(fields[7])}
        elif line == "VERIFY_PASS":
            verified = True
        else:
            raise ValueError(f"Unexpected benchmark output: {line!r}")
    assert result and verified and result["worker_hashes"] == list(expected)
    assert result["sample_count_reported"] == len(samples) >= 5
    assert 1000 <= result["duration_ms"] <= 180000
    assert samples[0]["seconds"] <= 0.1
    assert all(a["seconds"] < b["seconds"] for a, b in zip(samples, samples[1:]))
    duration = result["duration_ms"] / 1000
    assert samples[-1]["seconds"] >= duration - 0.02
    energy = {key: 0.0 for key in ("mpu_mw", "five_volt_mw")}
    for before, after in zip(samples, samples[1:]):
        start, end = before["seconds"], min(after["seconds"], duration)
        if end <= start:
            continue
        fraction = (end - start) / (after["seconds"] - start)
        for key in energy:
            end_power = before[key] + (after[key] - before[key]) * fraction
            energy[key] += (before[key] + end_power) * (end - start) / 2
        if end >= duration:
            break
    result.update({
        "duration_s": round(duration, 3),
        "sample_count": len(samples),
        "peak_cpu_millicelsius": max(s["cpu_millicelsius"] for s in samples),
        "mpu_energy_j": round(energy["mpu_mw"] / 1000, 4),
        "five_volt_energy_j": round(energy["five_volt_mw"] / 1000, 4),
        "mpu_average_mw": round(energy["mpu_mw"] / duration, 2),
        "five_volt_average_mw": round(energy["five_volt_mw"] / duration, 2),
    })
    return result


def parse_run(stdout: str, count: int, expected: tuple[str, str],
              phases: list[tuple[str, int, int]]) -> dict:
    lines = stdout.splitlines()
    parsed = {}
    position = 0
    for label, khz, uv in phases:
        assert lines[position] == f"PHASE {label} {khz} {uv}"
        position += 1
        end = lines.index(f"END_PHASE {label}", position)
        parsed[label] = parse_phase(lines[position:end], count, expected, khz, uv)
        position = end + 1
    assert lines[-1] == "FIXED_WORK_ENERGY_PASS" and lines[-2].startswith("GUARD ")
    assert position == len(lines) - 2
    guard = json.loads(lines[-2].removeprefix("GUARD "))
    assert guard["state"] == "feeding" and guard["nowayout"]
    summary = {"guard_pings": guard["pings"], "phases": parsed, "by_frequency": {}}
    for mhz in (350, 700):
        items = [parsed[label] for label, khz, _ in phases if khz == mhz * 1000]
        assert len(items) == 2
        summary["by_frequency"][str(mhz)] = {
            key: round(statistics.mean(x[key] for x in items), 4)
            for key in ("duration_s", "mpu_energy_j", "five_volt_energy_j",
                        "mpu_average_mw", "five_volt_average_mw")
        }
    high = summary["by_frequency"]["700"]
    low = summary["by_frequency"]["350"]
    summary["350_over_700_energy_ratio"] = {
        "likely_mpu": round(low["mpu_energy_j"] / high["mpu_energy_j"], 4),
        "five_volt_channel": round(low["five_volt_energy_j"] / high["five_volt_energy_j"], 4),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    version, low_uv, review = check_artifacts(args.profile)
    if not args.execute:
        print(json.dumps({"ready": True, "profile": args.profile,
                          "calibration_needed": not PLAN.exists()}, indent=2))
        return
    state = ram.ram_state("6.18.48-perrier-" + version)
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    current = json.loads(ram.CURRENT.read_text())
    assert current["status"] == "interactive" and current["profile"] == args.profile
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") +
                                        "-fixed-work-energy-" + version)
    directory.mkdir(mode=0o700)
    report = {"passed": False, "profile": args.profile,
              "kernel": state["kernel"], "boot_id": state["boot_id"],
              "started": started.isoformat(), "audit_sha256": sha(AUDIT),
              "binary_sha256": review["arm_sha256"]}
    uploaded = False
    try:
        upload_binary()
        uploaded = True
        preflight(version)
        if PLAN.exists():
            plan = json.loads(PLAN.read_text())
            assert plan["audit_sha256"] == sha(AUDIT)
            assert plan["arm_sha256"] == sha(ARM)
            assert plan["native_sha256"] == sha(NATIVE)
            count = plan["iterations_per_worker"]
            expected = tuple(plan["expected_hashes"])
            assert expected == reference(count)
        else:
            assert args.profile == "cpu-dvfs-trial"
            calibration_count = 20000000
            calibration_expected = reference(calibration_count)
            calibration_script = control_script(
                [("calibration", 350000, low_uv)], calibration_count,
                calibration_expected)
            (directory / "calibration-command.sh").write_text(calibration_script)
            calibrated = ram.remote(calibration_script, timeout=230)
            (directory / "calibration-stdout.log").write_text(calibrated.stdout)
            (directory / "calibration-stderr.log").write_text(calibrated.stderr)
            if calibrated.returncode or not calibrated.stdout.endswith("FIXED_WORK_ENERGY_PASS\n"):
                raise RuntimeError("calibration failed")
            lines = calibrated.stdout.splitlines()
            assert lines[0] == f"PHASE calibration 350000 {low_uv}"
            end = lines.index("END_PHASE calibration")
            assert lines[-1] == "FIXED_WORK_ENERGY_PASS"
            calibration_lines = lines[1:end]
            assert calibration_lines[-1] == "VERIFY_PASS"
            result_fields = next(line.split() for line in calibration_lines
                                 if line.startswith("RESULT "))
            assert len(result_fields) == 8 and int(result_fields[1]) == calibration_count
            assert result_fields[3:5] == list(calibration_expected)
            elapsed_ms = int(result_fields[2])
            assert 100 <= elapsed_ms < 180000
            count = round(calibration_count * 30000 / elapsed_ms / 1000000) * 1000000
            count = max(20000000, min(400000000, count))
            expected = reference(count)
            plan = {"created_at": datetime.now(timezone.utc).isoformat(),
                    "audit_sha256": sha(AUDIT), "arm_sha256": sha(ARM),
                    "native_sha256": sha(NATIVE),
                    "calibration_boot_id": state["boot_id"],
                    "calibration_iterations": calibration_count,
                    "calibration_duration_ms": elapsed_ms,
                    "iterations_per_worker": count,
                    "expected_hashes": list(expected),
                    "target_350mhz_duration_ms": 30000}
            PLAN.write_text(json.dumps(plan, indent=2) + "\n")
            report["calibration"] = {"iterations_per_worker": calibration_count,
                                     "duration_ms": elapsed_ms,
                                     "worker_hashes": result_fields[3:5]}
        assert 20000000 <= count <= 400000000
        assert expected == reference(count)
        phases = [("high_a", 700000, 1215400),
                  ("low_a", 350000, low_uv),
                  ("low_b", 350000, low_uv),
                  ("high_b", 700000, 1215400)]
        command = control_script(phases, count, expected)
        (directory / "command.sh").write_text(command)
        result = ram.remote(command, timeout=800)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        report["returncode"] = result.returncode
        if result.returncode or not result.stdout.endswith("FIXED_WORK_ENERGY_PASS\n"):
            raise RuntimeError("fixed-work command failed")
        summary = parse_run(result.stdout, count, expected, phases)
        report.update(passed=True, plan=plan, summary=summary)
    except BaseException as exc:
        report["error"] = repr(exc)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        if uploaded:
            try:
                ram.remote("rm -f " + TEMP + "\ntest ! -e " + TEMP + "\n")
            except Exception:
                pass
        request_recovery(args.profile)
    print(json.dumps({"run": str(directory), "passed": report["passed"],
                      "summary": report.get("summary", {}).get("by_frequency"),
                      "energy_ratio": report.get("summary", {}).get("350_over_700_energy_ratio"),
                      "error": report.get("error")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
