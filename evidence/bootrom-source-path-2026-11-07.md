# OMAP4460 ROM MMC source path and installed MLO location

Scope: offline disassembly of the captured 48 KiB ROM and byte reads from
the existing eMMC backup. No panel command or device state change.
Addresses are the ROM's low alias (add `0x40000000` for its physical alias).

## Source dispatch

The ROM source table at `0x37660` has three callback words per source.
Sources 5, 6, and 7 all use open callback `0x33af4`, read callback
`0x33bba`, and close callback `0x33c70` (Thumb pointers are one higher in
the table). In `0x36d08`, source 5 selects MMC controller index 0, source
6 selects index 1, and source 7 selects index 2. These are three
variants of the same MMC storage implementation.

The normal serial capture prints the Cisco MLO 1.41.0 banner and then U-Boot.
The existing live partition comparison established that the installed MLO
matches the CE9.9.0 package byte for byte. The U-Boot banner alone does not
expose the ROM's source code, but the board's eMMC is present and the exact
first-stage image is in its user area.

The exact signed MLO's `0x40304794` reads the low byte of `0x4a326000` as
its inherited boot-source code. Its dispatcher at `0x403066b8` compares
that code with 5 (`MMC/SD1`) and 6 (`EMMC`) and calls the storage loader
only for those two cases; the other branch reaches a fatal routine at
`0x4030670c`. Because this exact MLO continues to U-Boot on the panel,
the successful path strongly implies code 5 or 6, assuming the inherited
field retains the ROM's boot code. The serial capture does not include
the low-byte value, so it does not distinguish the two.

## Raw-slot progression

In `0x33af4`, the open callback initializes the boot-context image mask to
`0x11`. After MMC initialization, a nonzero controller index takes the raw
path at `0x33b86`–`0x33bb8`: it sets the internal reader mode to 1,
the boot-context attempt count to 4, and a secondary mask to `0x410`.
The internal slot selector at card-context `+0x0c` starts at zero. On a
subsequent open, `0x33b10`–`0x33b1e` invokes `0x36cea` with `-1`; that
routine increments the selector until it reaches 3.

For reader mode 1, `0x33c16`–`0x33c22` calculates the physical sector as
`requested_section_sector + (slot_selector << 8) + loop_sector`.
`0x33c4e` calls `0x36c62` for each such sector, then `0x33c5c` advances
the destination by `0x200`. Thus the raw candidates begin at LBA 0, 256,
512, and 768. The saved eMMC user area contains the exact 41,024-byte MLO
only at the second of those starts:

| Slot | LBA | Byte offset | Exact CE9.9.0 MLO? |
| ---: | ---: | ---: | --- |
| 0 | 0 | `0x00000` | No |
| 1 | 256 | `0x20000` | Yes; SHA-256 `2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427` |
| 2 | 512 | `0x40000` | No; zero-filled start |
| 3 | 768 | `0x60000` | No; zero-filled start |

Both 2 MiB eMMC boot-area backups lack the MLO's first 512 bytes and
`CertPK_` marker in their full contents. Among the inspected raw slots and
boot areas, saved user-area slot 1 is the only identified source for the
stock MLO banner.

## What this establishes

The raw MMC callback and 256-sector slot progression fit the installed
image location exactly. This substantially supports the candidate-A
`0x33bba` read path for normal boot. It does **not** prove from a recorded
ROM latch whether source 5 or 6 is selected on this board, nor does
it prove that a modified TOC destination would pass the secure monitor.
Both sources share the same read callback, so that remaining source-code
distinction does not alter the callback's destination arithmetic.
