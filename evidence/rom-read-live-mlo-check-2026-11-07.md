# Live MLO check and bounded Boot ROM read preparation, 2026-11-07

## Installed MLO

Read exactly 41,024 bytes from `/dev/mmcblk0p1` over root SSH and compared
them on the PC with the recovered CE9.9.0 package's `MLO`. Both SHA-256 hashes
were `2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427`;
`cmp` returned zero. This confirms the **currently installed** first-stage
image, not only the saved backup. The saved full eMMC image's partition 1
(`isw`, starting at LBA 256) also matches for the same 41,024 bytes.

The root public-key record in this exact live MLO hashes to
`8b846a5a4bd78d86fdbeee1c4ce0ed074e91b9f501f80652d1b6084b1c0fa742`,
equal to the previously captured ROM MPKH in `omap-rom-asic-id.json`.
`tools/check_rom_mlo_key.py` establishes record/hash equality only, not
acceptance of altered firmware.

## Boot ROM access

The U-Boot `bootz` proof allows an unsigned Linux image to be booted in a
future specifically authorized boot test. No further U-Boot environment
change or reboot was made here. The running kernel's `/dev/mem` `read()` at
the correct physical base, `0x40030000`, had previously returned `EFAULT`.

Prepared `tools/rom_mmap_word_omap4460.S`: a static ARM Linux helper that maps
one 4 KiB page read-only at physical `0x40030000` and directly loads a **single
32-bit word in user mode**. It writes to stdout from its stack, avoiding the
earlier kernel fault path caused by `write(1, mapped_address, ...)`. The binary
compiled and its syscall/physical-page instructions were inspected; the host
QEMU run reached the expected `/dev/mem` open failure.

Automatic approval review initially rejected the upload because it writes
and changes permissions on a file in the panel's RAM-only `/tmp`, while the
workspace `AGENTS.md` says investigation only and read-only device commands.
The owner then explicitly authorized this one temporary RAM helper, its one
four-byte read, and removal. The uploaded file was read back and SHA-256
verified against the local build (`c9dd27d7ce9fe1d7597ed468ffe257247eda308cb9dddf1f2471bff5a0573d58`).

The single mapped user-mode read at physical `0x40030000` succeeded with exit
code zero and returned four bytes: `42 02 00 ea` (little-endian ARM word
`0xea000242`). The helper was removed from `/tmp`. A fresh root SSH connection
succeeded, uptime continued to increase, and the kernel log tail had no new
fault. This proves at least the first word of the 48 KiB ROM is accessible
through this mapping; it is **not** yet a complete Boot ROM dump. No persistent
device storage or boot setting was changed during this read.

For the full dump, `tools/rom_mmap_dump_omap4460.S` was prepared and
compiled locally. It reads twelve 4 KiB pages, copies each into a stack
buffer in user mode, and outputs each complete page before touching the next.
Its source and disassembly were reviewed. Local binary SHA-256:
`9dc59c852d241997e1f7907d822614aa3cc1c69f4c1da3877a1728becb8a961e`.
The owner explicitly authorized one run of this larger helper after the
four-byte test. It was uploaded to RAM-only `/tmp`, read back, and matched the
local SHA-256. The one run exited zero and delivered exactly **49,152 bytes**,
the 48 KiB OMAP4460 Boot ROM range. Saved image:
`evidence/omap4460-bootrom-2026-11-07.bin`, SHA-256
`7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff`.
Its first word matches the separate four-byte probe. It begins with ARM
exception-vector instructions and contains expected loader names such as
`2ND`, `MLO`, `ULO`, and `PRIMAPP`. Later pages include zero-filled regions;
this is not a byte-for-byte comparison with an independent ROM reference.

The full-dump helper was removed from `/tmp`. Root SSH stayed reachable,
uptime continued to increase, and the kernel log tail contained no new fault.
No persistent device storage or boot setting was changed for either ROM read.
