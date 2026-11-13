# Touch 10 U-Boot boot-path development

This is a controlled way to boot a new kernel through the installed, signed
Cisco MLO and U-Boot while preserving the factory kernel and root filesystem.
The first image is deliberately serial-only. It does not probe the display,
touch controller, storage, GPIOs, or watchdog.

## Verified result

On 2026-11-10, `perrier-cold01` booted from U-Boot after a **software reset**.
The serial trace shows U-Boot saving `bootcmd=run normalboot` to eMMC partition
8, loading the audited zImage and DTB from new files on partition 14, executing
`bootz`, reaching Linux `6.18.48-perrier-cold01` PID 1, and rebooting after ten
seconds. The subsequent factory boot reached Linux `3.4.113+` with `phoenix`
running. Partition 8 had its exact pre-test SHA-256 again:
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
See [the run result](../runs/20261110T090353Z-coldboot-e2c4a0/result.json)
and [timestamped serial trace](../runs/20261110T090353Z-coldboot-e2c4a0/serial.log).

The owner then authorized a separate **physical power-on** test of the same
audited image. It passed on 2026-11-10: the serial trace shows the power-on
MLO/U-Boot path, the same new-kernel markers and restart, and the factory boot.
Root SSH reported `phoenix` running and p8 again matched the exact original
hash. See [the physical run result](../runs/20261110T091103Z-coldboot-b56e25/result.json)
and [its serial trace](../runs/20261110T091103Z-coldboot-b56e25/serial.log).

## Repeatable sequence

From the workspace root, prepare and review the image entirely on the PC:

```sh
python3 development/perrier-coldboot/build_probe.py
python3 development/perrier-coldboot/audit_probe.py
python3 development/perrier-coldboot/build_oneshot.py
python3 development/perrier-coldboot/audit_oneshot.py
```

`oneshot-manifest.json` names each exact file, hash, size, load address, and
U-Boot command. `oneshot-p8.bin` is a 256 KiB CRC-checked environment image;
the only changed variable is `bootcmd`. The full original p8 bytes are kept
privately in `stock-p8-before.bin`, and the full eMMC backup is under
`backups/touch10-2026-11-07`.

After the audit, `stage_oneshot.py` copies only the two hash-named test files
into `/mnt/base/touch10-dev/` on p14 and reads them back. It never touches
the factory `/active/kernel` or `/active/rootfs`. `run_oneshot.py` performs
one p8 write/readback, starts passive serial logging, requests one software
reboot, and checks the new-kernel markers, stock return, and original p8 hash:

```sh
python3 development/perrier-coldboot/stage_oneshot.py
python3 development/perrier-coldboot/run_oneshot.py --timeout 300
```

The physical-power mode uses `run_oneshot.py --power-cycle` with a 15-minute
arming window. It waits for the user to remove and reconnect PoE once, with
USB left attached, and disarms the candidate if no cycle occurs. Each run
writes p8, so check that the exact candidate and test are authorized before
starting another run.

The one-shot U-Boot command first changes `bootcmd` back to `run normalboot`
and calls `saveenv`. Only after that succeeds does it load the test zImage at
`0x84000000`, the DTB at `0x83000000`, and call `bootz`. A failed load, failed
`saveenv`, or a returning `bootz` falls through to the unchanged factory
`normalboot` command. If the test kernel hangs after handoff and the watchdog
is inactive, one physical power cycle may still be required. The single-copy
p8 write remains the main recovery risk; the exact baseline is checked both
before and after each attempt.

## Next image

The separate [ram59 watchdog image](../perrier-watchdog/README.md) now carries
the full ram58 environment plus the unmodified mainline `omap_wdt` driver and
a feeder using `/dev/watchdog0`. It passed a kexec hardware-expiry proof on
2026-11-10, returning stock with p8 unchanged. Its full-image U-Boot candidate
and load ranges are audited. `tools/touch10_uboot.py` provides the staged
one-shot session, RAM SSH/Qt startup, host lease, and stock return checks.
The first full-image U-Boot run reached ram59 and its watchdog feeder but
could not start Ethernet or touch from the bootloader state. Its unrenewed
lease returned stock automatically, with p8 exactly restored. See the ram59
record for the failed SSH criterion and the next Ethernet candidate. The
minimal cold01 physical power-on proof above remains the only power-on
kernel test so far.

Ram60 has since passed the full U-Boot Ethernet/SSH and hardware-expiry test
after a software reset, returning stock with p8 exactly restored. It is now
the default kernel-test profile in `tools/touch10_uboot.py`. See the
[Ethernet/U-Boot record](../perrier-cold-ethernet/README.md). Future kernel
tests use this one-shot route directly; kexec remains available for specific
diagnostics and is not a required pre-test step.
