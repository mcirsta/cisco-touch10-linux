# Perrier watchdog and interactive U-Boot image

Ram59 carries forward the working ram58 display, touch, keypad, backlight,
Ethernet, thermal, Qt, and RAM SSH support. It adds the unmodified mainline
`omap_wdt` driver and a userspace feeder using `/dev/watchdog0`. The previous
ram58 image and its register-based feeder remain available separately.

The added DT target is WDT2 at `0x4a314000`, described using the upstream
OMAP4 clock and interrupt data. No regulator, pinmux, voltage, or GPIO output
is added. The disabled legacy WDT2 node under `/ocp` stays disabled. The
`ti,no-reset-on-init` and `ti,no-idle-on-init` properties preserve an inherited
timer until the mainline driver takes over. Its `early_enable` parameter
starts a 120-second timer at driver probe, including on a power-on boot.

The kernel's initial watchdog feeding has a 60-second open deadline. The
feeder verifies the board, `OMAP Watchdog` identity, nowayout, and 120-second
timeout before announcing readiness. It feeds every five seconds, allows
90 seconds for the first SSH lease, and then requires renewal within 60
seconds. Lease expiry requests software reboot. The `expire` command stops
feeding while keeping the descriptor open, allowing an actual hardware reset.
No magic-close or watchdog-disable operation is issued by the feeder.
Kernel execution before the watchdog driver probes is not yet covered by
this timer; a very early hang can still require a physical power cycle.

## Verified recovery

The [ram59 kexec run](../runs/20261110T092452Z-interactive-d8f755/result.json)
passed on 2026-11-10. SSH was available with the new driver feeding WDT2;
the eMMC was read-only and no eMMC filesystem was mounted. After more than
120 seconds of healthy operation the host sent `expire`. The hardware reset
the panel and stock SSH/Phoenix returned 153.6 seconds later. The exact p8
hash was unchanged. The proof is saved separately in
`development/perrier-ramenv/native-watchdog/watchdog-proof.json`, tied to the
new feeder hash. It does not replace the older feeder's proof.

## Build and audit

From `/home/marius/ext_proj/touch10`:

```sh
python3 development/perrier-watchdog/build_image.py
python3 development/perrier-watchdog/audit_image.py
python3 tools/touch10_ram.py session --profile native-watchdog --minutes 3 --prove-recovery
```

The builder copies the audited ram58 filesystem and config into a separate
`native-watchdog` directory. The audit permits only watchdog config additions,
two new DT nodes, the feeder executable, and its startup checks. It also
verifies the packed initramfs, source and artifact hashes, unchanged hardware
properties, and the existing 32 MiB kexec image reservation. The ARM feeder's
wrong-board rejection is checked under QEMU before a hardware run.

## One-use U-Boot session

After the hardware expiry proof passes:

```sh
python3 tools/touch10_uboot.py prepare --profile native-watchdog
python3 tools/touch10_uboot.py session --profile native-watchdog --minutes 3 --prove-recovery
```

`prepare` is entirely offline. It generates a DTB with fresh host entropy,
builds a CRC-correct 256 KiB one-shot p8 candidate, and independently audits
it. The zImage is loaded at `0x84000000` and DTB at `0x83000000`; both are
disjoint from the decompressed kernel. The only environment variable changed
is `bootcmd`. The command saves `bootcmd=run normalboot` before loading either
test file, using the same template proven with the minimal cold01 kernel.

`session` stages and reads back the two hash-named files on p14, writes and
reads back p8 once, captures UART, and requests one software reboot. Once
RAM SSH is ready, it checks that U-Boot already restored the exact factory
p8, validates the read-only eMMC and RAM mounts, starts the bundled Qt app,
and renews the host lease. It then requests stock return, checks SSH/Phoenix
and p8 again, and saves all evidence under `development/runs/`.

The manifest is marked consumed when arming begins; run `prepare` again to
get fresh entropy for another attempt. If the software reboot is rejected
and the original stock boot remains alive, the runner disarms p8. It never
retries a reset on failure. Each session performs a persistent p8 write and
requires authorization covering that exact attempt.

During a session, use the same RAM SSH, file transfer, Qt restart, and
`python3 tools/touch10_ram.py recover` commands as the kexec environment.
`--power-cycle` is available for a separately arranged physical power-on
test, with a 15-minute arming window.

## First full-image U-Boot attempt

The owner-authorized [ram59 U-Boot attempt](../runs/20261110T093703Z-uboot-ram59-481e68/result.json)
ran on 2026-11-10. U-Boot saved the factory environment, loaded the complete
17,038,240-byte zImage and DTB, and started ram59. The mainline watchdog
probed at 1.50 seconds and the feeder reached readiness. The test did not
reach RAM SSH: EHCI registered, but the USB LAN device never enumerated, and
the stock-inherited touch setup returned I2C `-121`. No Qt test was possible.

The unrenewed host lease caused the feeder's automatic software return after
90 seconds. Stock Linux and Phoenix returned on a new boot ID with p8 exactly
restored. This proves the full-image handoff and unattended startup-failure
recovery, but not the planned full-image hardware-expiry check or interactive
peripheral operation through U-Boot. The earlier kexec hardware-expiry proof
above remains valid for this feeder.

The next [Ethernet candidate](../perrier-cold-ethernet/README.md) supplies the
stock-verified PHY clock, reset lines, and ULPI pinmux through mainline DT
drivers. Ram60 subsequently passed the U-Boot network/SSH and hardware-expiry
test and is now the default U-Boot development profile. The original ram59
artifact and its consumed one-use manifest are retained as evidence.
