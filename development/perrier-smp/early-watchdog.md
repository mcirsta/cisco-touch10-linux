# Early watchdog boundary for an SMP U-Boot trial

The one-shot U-Boot runner restores the factory `bootcmd` before loading a
RAM kernel. Its present hardware watchdog begins when mainline `omap_wdt`
probes. An SMP failure in decompression, early memory setup or initramfs
unpack can precede that probe, so the current 120-second feeder cannot
guarantee automatic recovery from those failures.

Offline analysis of the CE9.9.0 Touch 10 U-Boot code image
`firmware/codec-ce9.9.0/analysis/touch10-ce990-uboot-code.bin`
(SHA-256 `dc6c33ff20c0a490cba102298249ba0b0383edd8992f55a2ad57d2ef322a4844`)
found a function at `0x80e808ee` that writes `0xaaaa`, waits, then writes
`0x5555` to `0x4a314048`. This is the OMAP WDT2 stop sequence. Its caller
at `0x80e8090c` runs during U-Boot initialization. The binary's command
strings include memory write (`mw`), memory display (`md`), integer test
(`itest`) and delay (`sleep`). This establishes that the existing U-Boot
boot path actively stops WDT2 before invoking the one-shot environment.
The wait helper at `0x80e808e6` polls WPS until zero after the first write;
the stop routine does not wait after the second write. The sole literal
`0x4a307830` (WDT2 clock control) is in a broad PRCM address table, not a
dedicated watchdog enable sequence. Neither observation proves the clock's
state by the time `bootcmd` executes.

Mainline `drivers/watchdog/omap_wdt.c` and `omap_wdt.h` define WDT2's
posted-write protocol. Start requires `0x20` at control offset `0x24`,
the 120-second load value `0xffc40000` at offset `0x2c`, a trigger write at
offset `0x30`, and the `0xbbbb`/`0x4444` start sequence at offset `0x48`.
Every posted write must complete according to the WPS register at offset
`0x34`. A blind sequence of `mw` commands has not been tested. The WDT2
functional clock's state when U-Boot executes `bootcmd` also needs checking;
the initialization-time stop sequence alone does not establish that state.

Before booting an SMP candidate from U-Boot:

1. Make a one-shot environment variant that checks WDT2 clock/WPS state,
   arms 120 seconds, and demonstrates a changing WCRR counter using serial
   readback, then boots an already qualified single-core RAM image.
2. Audit that the variant changes only `bootcmd`, saves the factory path
   before any WDT instruction, and leaves the prior zImage/DTB load ranges,
   read-only eMMC policy and host lease intact.
3. Verify a known-good RAM kernel takes over WDT2 and returns to stock.
   Then test SMP first with `nosmp` to separate U-Boot handoff from CPU1,
   followed by CPU1 only if the parser and watchdog both pass.

No early-WDT variant has been written to the panel. The ram105 network boot
and recovery did not change WDT2 startup behavior.

On 2026-11-12 a read-only stock Linux probe tried to read WDT2 WCRR at
`0x4a314028` through `/dev/mem` using stock `dd`; the kernel returned
`Bad address` and no register bytes. This does not establish the U-Boot
clock or counter state. The next observation should use audited U-Boot
`md` commands in a known-good one-shot RAM boot, before any attempt to arm
WDT2 or boot an SMP candidate. The ram107 network test completed with the
existing driver-probe watchdog and exact factory recovery.
