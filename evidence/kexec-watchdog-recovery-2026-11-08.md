# Live kexec and watchdog recovery qualification, 2026-11-08

The owner requested continuing kexec/watchdog work so development can run
without physical power cycling. The tests below used the established root
SSH key and passive service UART capture. Helpers and payloads were staged
only in the verified `/tmp` tmpfs, checked by full readback, and disappeared
on reset. No boot environment, GPT, bootloader or installed firmware file
was written by these tools. There was no live kernel-code patch or direct
watchdog MMIO write.

## Exact-kernel findings

The package zImage was extracted at offset `0x390`, decompressed into a raw
ARM Image, and loaded in IDA at virtual `0xc0008000` as **32-bit ARM**.
Names/addresses were cross-checked with the running kernel's saved
[`/proc/kallsyms`](ce990-kallsyms-2026-11-08.txt).
[Disassembly](ce990-kexec-watchdog-disasm-2026-11-08.txt) is the primary
binary evidence; the decompiler can incorrectly treat runtime data in this
raw Image as constants, so those pseudocode expressions are not proof.

- `kernel_kexec` at `0xc008b2ec` calls `kernel_restart_prepare`, then
  `machine_shutdown` and `machine_kexec` (`0xc00141fc`). Normal device
  shutdown therefore runs before the jump.
- `omap_wdt_shutdown` at `0xc02fbff8` tests the watchdog's open/users field
  (`private_data + 8`). When open, it calls `omap_wdt_disable` at
  `0xc02fbef8` and releases runtime PM. Merely leaving the stock feeder
  alive would **disable** recovery during kexec shutdown.
- With `CONFIG_WATCHDOG_NOWAYOUT=y`, `omap_wdt_release` at `0xc02fbf90`
  only clears that open/users field. It does not disable the hardware.
  Consequently a watchdog armed and then closed remains active, while
  the shutdown callback returns early. This behavior was tested below.
- The stock `watchdog` process owns `/dev/watchdog`, executes `/bin/watchdog`,
  and registers a SIGTERM handler. The test deliberately uses SIGKILL when
  transferring ownership, so its userspace handler does not interfere.
- Original ARM tags are readable in [`/proc/atags`](ce990-atags-2026-11-08.bin).
  The loader preserves board-revision and memory tags, replaces cmdline/
  initrd tags, and places the tags at entry minus `0x7000`, matching this
  kernel's `machine_kexec` code.

## Pinned artifacts and build

[Manifest](../development/ram/manifest.json) records sizes/hashes of the
exact factory extraction, static loader, helper and stall image.

- kexec-tools from its maintainer's
  [kernel.org repository](https://git.kernel.org/pub/scm/utils/kernel/kexec/kexec-tools.git/),
  commit `0fd0d8e9ea975696fdc05ad267a65f3efd415612` (`2.0.32.git`).
  [`development/build-kexec.sh`](../development/build-kexec.sh) uses Zig
  0.15.2 to produce a static ARMv7/musl executable. Optional compression
  libraries and Xen are disabled; the factory raw zImage/gzipped initramfs
  are supplied directly. The wrapper drops only the optional GNU linker-map
  output flag unsupported by this Zig driver.
- Modern `--debug` sets `KEXEC_DEBUG` (`0x10`), which this old kernel rejects
  with EINVAL. The initial rejected load was unloaded/cleaned up; the passing
  command uses `--kexec-syscall` without `--debug` (flags `0x280000`).
- [`arm_watchdog.c`](../development/ram/arm_watchdog.c) uses only the stock
  watchdog ioctls: open, set/get timeout, keepalive, close. Allowed timeouts
  are 15 and 120 seconds. It has no register or storage access.
- [`kexec_stall.S`](../development/ram/kexec_stall.S) builds a 144-byte
  zImage-shaped ARM payload. It emits `TOUCH10_KEXEC_RAM_STALL` through the
  already configured UART3, then loops with IRQ/FIQ disabled. Its only
  peripheral write is a character to the UART transmit register.
  [IDA review](kexec-stall-review-2026-11-08.txt) confirms that behavior.

## Live results

| Test | Result and evidence |
| --- | --- |
| Pause existing feeder, with delayed resume fallback | Passed: watchdog reset occurred roughly 60 seconds after the pause; stock root SSH returned. [Run](../development/runs/20261108T083410Z-watchdog-recovery-609b4c/result.json) |
| Load and unload exact factory kernel/initramfs, without execution | Passed: `kexec_loaded` changed `0 → 1 → 0`; boot ID stayed the same. [Run](../development/runs/20261108T083806Z-kexec-load-check-9b7c6b/result.json) |
| Arm 15 seconds, close fd, wait for reset | Passed: helper reported `WATCHDOG_ARMED_CLOSED=15`; hardware reset and stock root SSH returned. Detached restart fallback was 45 seconds. [Run](../development/runs/20261108T084041Z-watchdog-close-recovery-1ea650/result.json) |
| Arm 120 seconds, close fd, execute UART/stall payload through kexec | Passed: payload marker at `08:42:13.635 UTC`; watchdog reboot began about 120 seconds later; stock root SSH and `phoenix` returned. [Result](../development/runs/20261108T084207Z-kexec-watchdog-52a644/result.json), [serial log](../development/runs/20261108T084207Z-kexec-watchdog-52a644/serial.log) |

All passing reset tests retained p8 SHA-256
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
The final stock boot ID was `84103357-e93f-4fc9-8fe0-6013133414e4`, with
Linux `3.4.113+`, `phoenix` running, and `kexec_loaded=0`. No password or
physical cable operation was required during these tests.

## What this qualifies

Root SSH can stage a hash-checked RAM image, `kexec_load` can accept ARM
segments, kexec can enter our code, and a closed-descriptor watchdog survives
the stock kernel's shutdown and that stalled payload. The loader constrains
destinations to the observed low RAM range `0x80000000–0x98ffffff`.

A new Linux kernel/DTB has **not** yet been executed by kexec. Its startup
could reset the watchdog, gate its clock, or disable unused clocks. Before
the first new-kernel trial, audit the actual OMAP hwmod/ti-sysc/clock/watchdog
initialization, not just Kconfig. The new image must preserve the inherited
120-second timer until it can enforce a bounded test and return to stock.
The first kernel should omit the watchdog driver unless its boot behavior
has been reviewed to preserve an already-running timer. Excluding a driver
alone does not prove that its parent clock/module will remain active.
