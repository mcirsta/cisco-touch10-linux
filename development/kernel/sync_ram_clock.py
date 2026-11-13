#!/usr/bin/env python3
"""Set only the volatile RAM kernel clock from the host and verify RTC safety."""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SSH = ["ssh", "-F", str(ROOT / "access/ssh_config"), "touch10-ram"]


def read_state():
    result = subprocess.check_output(SSH + [
        "uname -r; date -u +%s; cat /sys/class/rtc/rtc0/since_epoch; "
        "cat /run/qt.pid; cat /run/guard.json"], text=True, timeout=12)
    lines = result.splitlines()
    assert len(lines) >= 5, result
    return {"kernel": lines[0], "system_epoch": int(lines[1]),
            "rtc_epoch": int(lines[2]), "qt_pid": int(lines[3]),
            "guard": json.loads(lines[4])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", default="6.18.48-perrier-ram100")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "development/kernel/out/ram-clock-sync.json")
    args = parser.parse_args()
    before = read_state()
    assert before["kernel"] == args.kernel
    assert before["guard"]["state"] == "feeding"
    epoch = int(time.time())
    result = subprocess.run(SSH + [f"date -u -s @{epoch}"],
                            capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise RuntimeError(result.stderr + result.stdout)
    after = read_state()
    now = int(time.time())
    report = {"before": before, "after": after, "host_epoch_sent": epoch,
              "host_epoch_after": now, "passed": after["kernel"] == before["kernel"]
              and abs(after["system_epoch"] - now) <= 5
              and 0 <= after["rtc_epoch"] - before["rtc_epoch"] <= 20
              and after["qt_pid"] == before["qt_pid"]
              and after["guard"]["state"] == "feeding"}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
