# OMAP4460 Boot ROM read attempt via root SSH, 2026-11-07

The owner asked whether the established root SSH access permits reading the
on-chip Boot ROM. This was an investigation-only test. **Correction:** the
[TI OMAP4460 memory map](https://www.ti.com/jp/lit/pdf/swpu316) places the
48 KiB ROM at physical `0x40030000`–`0x4003bfff`, with
`0x40000000`–`0x4002ffff` reserved. This is distinct from the backed-up eMMC
MLO and U-Boot partitions. The historical probe below used an incorrect
address and therefore did not test ROM readability.

On the running Touch 10, `/dev/mem` exists; the extracted kernel config has
`CONFIG_DEVMEM=y` and `CONFIG_STRICT_DEVMEM` unset. A bounded 4 KiB `read()`
at physical `0x40028000` returned `Bad address` and zero bytes. A temporary
ARM helper run from the RAM root filesystem then used a read-only `/dev/mem`
`mmap2` to copy the first 16 bytes; it exited successfully and returned
16 zero bytes. Those bytes are saved as `rom-linux-first16-2026-11-07.bin`.

A second helper mapped 48 KiB starting at the same incorrect address and
attempted to stream it to the PC. The kernel reported `Unhandled fault: external abort on
non-linefetch (0x018)` at virtual `0xb6fbb000` in
`iov_fault_in_pages_read`. The mapped base visible in the fault report is
`0xb6fb4000`; the fault offset `0x7000` corresponds to physical
`0x4002f000`, which is in the reserved region on OMAP4460. No full-range
bytes were captured. The fault log is
`rom-linux-full-map-kernel-fault-2026-11-07.log`.

Afterward, a fresh root SSH connection succeeded and the normal `phoenix`
process was still running. The helpers were removed from the panel's RAM
`/tmp`; no eMMC, environment, firmware, or boot setting was changed. Live
reads stopped after the fault. This result establishes only that the old
probe hit a reserved region; it says nothing about accessibility or security
policy at the actual OMAP4460 ROM address. A correctly addressed live probe
would need its own bounded risk review.

The helper sources are `tools/rom_mmap_probe.S` and
`tools/rom_mmap_dump.S`. Both are marked historical and must not be reused as
ROM probes without correcting and reviewing the address.

## Corrected-address read-only check

Later on 2026-11-07, a single 16-byte `dd` read was attempted at the
correct physical base `0x40030000` using `/dev/mem`, `bs=16`,
`skip=67121152`, and `count=1`. It returned `Bad address` with zero bytes.
This is the kernel's `/dev/mem` `read()` path, which also returned `Bad
address` at the old address; it does **not** establish whether a mapped read
of the actual ROM is possible. No mapped read at the corrected address was
attempted. A subsequent root SSH connection succeeded, `phoenix` was still
running, and the visible kernel trace tail was the older fault at uptime
5170 seconds, not a new fault from this check. No device storage was changed.
