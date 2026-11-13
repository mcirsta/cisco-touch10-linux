# Live one-boot U-Boot `bootz` proof, 2026-11-07

The owner explicitly authorized one partition-8 environment write and one
boot test. The service UART was captured continuously in
`uboot-bootz-probe-2026-11-07/live-serial.log` (SHA-256
`c0c482cd293ef01190539b6450373f27e269a01dc047bf633d90bc47ad2584db`).
This record distinguishes eMMC changes from RAM-only actions.

## Environment and console

Before the host write, a read-only live hash of eMMC partition 8 matched the
backup: `bd527afd42a26a7b983775d05c33c1860c879ef61f38da0c0329f92610839eca`.
The host then wrote exactly the 262,144-byte reviewed environment candidate
to `/dev/mmcblk0p8` and read it back; SHA-256 matched the candidate
`8aeadf4b483217c3ad94c772fb32ae63d4fedb175f7851edbad4476f761dd9bb`.
The sole instructed reboot followed.

U-Boot printed `Saving Environment to MMC... Writing to MMC(1)... done`,
`CONSOLE_READY`, and `TOUCH10>`. Its `printenv` showed
`bootcmd=run normalboot` and `normalboot` equal to the exact factory boot
command. Thus U-Boot itself made a second partition-8 write, as designed.
At the prompt, `mmc dev 1` and a read of blocks 285440–285951 into RAM
verified the saved environment's stored CRC `0x7c3bb000` equals U-Boot's
`crc32` over its 262,140 data bytes. The first `mmc read` attempt, before
selecting device 1, reported that device 0 was absent and wrote nothing.

## Unsigned zImage test

The exact factory `/active/kernel` (3,725,200 bytes) and `/active/rootfs`
(20,582,926 bytes) were loaded from eMMC into RAM at `0x84000000` and
`0x84800000`. `md.l` showed the raw zImage at `0x84000390`, with magic
`0x016f2818` at `+0x24`. The `mw.l` command changed only the second ARM
no-op instruction in **RAM**, at `0x84000394`, from `e1a00000` (`mov r0,r0`)
to `e1a01001` (`mov r1,r1`). A second `md.l` confirmed the changed word
and unchanged zImage header. No kernel or rootfs file on eMMC was edited.

`bootz 0x84000390 0x84800000` printed `Verifying Checksum ... OK`,
`Starting kernel ...`, then `Uncompressing Linux... done, booting the
kernel.` The checksum message is consistent with checking the unchanged
legacy initramfs; the exact U-Boot `bootz` trace has no Cisco certificate
verification call for the raw zImage. The serial login prompt appeared.
A fresh SSH session returned `uid=0(root)`, uptime 38 seconds, the normal
kernel command line, and a live `phoenix` process. This is a live proof that
the modified, unsigned zImage passed through this U-Boot's `bootz` path and
booted successfully. It does not imply that `bootm` or `booti` accepts
unsigned images.

## State left on the panel

After Linux boot, a read-only partition-8 transfer had SHA-256
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
Its stored and computed CRC are both `0x7c3bb000`; it contains 30 variables,
`bootcmd=run normalboot`, `autoupgrade=0`, no `bootdelay`, and a `normalboot`
value that byte-matches the original compiled factory boot command. This is
the intended persistent normal-boot state, but an additional ordinary reboot
has **not** been performed to observe it directly. The original invalid
environment bytes remain in the saved full eMMC backup.

The separate corrected-address Linux `/dev/mem` `read()` check returned
`Bad address` with no bytes. No mapped ROM read or Boot ROM dump was made.
This describes the state at the end of that boot test. A later user-mode
mapped read captured the complete 48 KiB ROM; see
`rom-read-live-mlo-check-2026-11-07.md`.

On 2026-11-08 the development workflow performed one ordinary software
reboot and observed the factory boot return through root SSH with a new boot
ID and `phoenix` running. P8 retained SHA-256
`f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
This later test observes the restored normal-boot environment successfully;
see `../development/runs/20261108T082341Z-reboot-stock-930ad1/result.json`
and `../DEVELOPMENT-WORKFLOW.md`.
