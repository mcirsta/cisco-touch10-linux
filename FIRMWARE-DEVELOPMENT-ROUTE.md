# Touch 10 replacement firmware route

Status: feasibility review on 2026-11-08. This document plans future work;
it does not authorize a device write or reboot. The workspace `AGENTS.md`
currently limits recovery work to investigation.

The pinned Nexus Q Reloaded comparison and Perrier adaptation gates are in
[`NEXUSQ-TO-PERRIER-PORT.md`](NEXUSQ-TO-PERRIER-PORT.md).
The key-only development runner, proven automatic stock reboot, and planned
kexec test loop are in [`DEVELOPMENT-WORKFLOW.md`](DEVELOPMENT-WORKFLOW.md).

## Proven starting point

- This panel runs Linux 3.4.113+ on the OMAP4460 ES1.1 Perrier board. The
  stock configuration enables Cisco's `CONFIG_MACH_OMAP4_PERRIER` board
  support. Its exact configuration is in
  [`evidence/ce990-kernel-config-2026-11-07.txt`](evidence/ce990-kernel-config-2026-11-07.txt).
- The signed ROM, MLO, and U-Boot chain remains installed. In a live test,
  this U-Boot loaded the factory zImage and initramfs into RAM, changed one
  zImage instruction **in RAM**, and booted it with `bootz`. Its factory
  `bootm` path checks the Cisco image signature. See
  [`evidence/uboot-bootz-live-proof-2026-11-07.md`](evidence/uboot-bootz-live-proof-2026-11-07.md).
- Root SSH, a service UART, and a full backup of the eMMC user and boot areas
  are available. The running root filesystem is a RAM initramfs; p14 is the
  active ext4 base filesystem mounted at `/mnt/base`. Its `/active` link
  points to `image2`. A read-only live check found 384.2 MiB free on p14.
- The current U-Boot environment in p8 uses `bootcmd=run normalboot`.
  `normalboot` loads `/active/kernel` and `/active/rootfs` from `mmc 1:e`
  and uses `bootm`. A previous authorized test proved the serial U-Boot
  prompt and `saveenv` work. See
  [`evidence/uboot-bootz-probe-2026-11-07/live-serial.log`](evidence/uboot-bootz-probe-2026-11-07/live-serial.log).
- GPT p12 is a nominal 512 MiB alternate system slot, but the backup has
  no ext4 superblock there and it is not a proven recovery system. P8 is a
  single 256 KiB environment copy. The full device backup is in
  [`backups/touch10-2026-11-07`](backups/touch10-2026-11-07).

## Development sequence

1. **Board data and toolchain.** Reconstruct a Perrier DT from stock boot
   logs, kernel config, sysfs, and hardware inventory. Compare it against
   the current upstream OMAP4460 DTS and bindings. Pin and verify an
   official kernel source release. The host has Clang, LLD, `dtc`, and
   `cpio` plus a validated Zig/musl ARM32 userspace cross-build setup; it has
   no downloaded target Linux tree yet.
   Cisco's corresponding GPL source would shorten this stage; the draft
   request is [`SOURCE-REQUEST.md`](SOURCE-REQUEST.md).
2. **Minimal RAM boot.** Build an ARM zImage and Perrier DTB with serial,
   clocks, interrupt controller, RAM, and a tiny embedded initramfs. An
   embedded initramfs simplifies the first trial. The preferred entry is now
   key SSH → tmpfs upload → kexec, using the proven closed-fd watchdog
   handoff. A reviewed RAM marker/stall payload has executed and recovered
   automatically. Before using a new kernel, audit its early watchdog and
   clock behavior so it preserves the inherited timer. The FDT handoff and
   minimal Linux 6.18.48 kernel have now passed RAM-only kexec tests. See the
   workflow's qualification record.
3. **Bring up devices one at a time.** Confirm serial shell, CPU/RAM,
   eMMC read-only, and SMSC95xx USB Ethernet. Then bring up OMAP DRM,
   the TC358765 DSI-LVDS bridge, backlight, and CYTTSP4 I2C touch.
   Upstream has OMAP4 DT support and a TC358765 bridge driver, but the
   stock board data and CYTTSP4 integration need porting or replacement.
4. **One-shot eMMC boot.** Stage the proven zImage/DTB under *new names*
   on p14, leaving `/active/kernel` and `/active/rootfs` intact. A reviewed
   one-shot p8 command would restore and save `bootcmd=run normalboot`
   **before** loading those new files and invoking `bootz`. This is a
   proposed experiment, not a tested persistent boot path. Start with
   the embedded initramfs; an ext4 rootfs on p12 can follow after the
   kernel's eMMC support and fallback are verified.
5. **Deliberate default selection.** Only after repeated successful boots,
   choose whether to keep a selectable factory path or make the new system
   the default. There is no demonstrated automatic OS fallback today, so
   a permanent boot change needs a separate rollback design.

## Exact boundary today

U-Boot's `bootz` executed an **unsigned, RAM-modified factory zImage**.
Independently, kexec now executes a minimal Linux 6.18.48 kernel with an
external Perrier DTB and embedded initramfs. Its early tests returned to stock
through the armed watchdog; the current RAM init uses a proven normal software
reboot after diagnostics, retaining the watchdog as fallback. Host-to-U-Boot
RAM transfer, an unsigned custom rootfs, and persistent **eMMC boot** have not
been tested.
The existing factory `bootm` command cannot be used as the assumed route
for an unsigned replacement. Any eMMC staging or p8 change is outside the
current investigation-only device scope until the owner authorizes that
specific candidate.
