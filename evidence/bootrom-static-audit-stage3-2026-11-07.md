# OMAP4460 Boot ROM static audit: stage 3 — signed image and sector tail

This stage uses the captured 48 KiB ROM, the exact CE9.9.0 MLO, the saved
eMMC image, and offline models only. No panel command or storage write was
made. ROM addresses below use the low alias. The previous stages contain
the ROM map and the range-clamp disassembly.

## Exact storage image and certificate chain

The saved eMMC user-area image contains a byte-identical copy of the
41,024-byte MLO at offset `0x20000` (SHA-256
`2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427`).
Its 512-byte outer TOC begins there. The MLO record starts at TOC offset
zero, names `MLO`, places the ISW section at relative offset `0x4000`, gives
it size `0x6040`, and sets its destination word at TOC `+0x10` to zero.

`analysis/bootrom/verify_mlo_chain.py` independently checks the image's
cryptographic chain using only Python's integer arithmetic and hashes:

| Item | Checked bytes and result |
| --- | --- |
| ROM root key | SHA-256 of the 276-byte root key record equals the MPKH returned by this unit's ROM ASIC-ID response. |
| `CertPK_` | Its 0x848-byte signed prefix has a valid RSA-2048 PKCS#1 v1.5 / SHA-256 signature under the root key. |
| `CertPPA` | Its 0xc4-byte signed prefix has a valid signature under key ID 2 from `CertPK_`; SHA-1 of its `0x31c0`-byte body matches the embedded digest. |
| `CertISW` | Its 0x238-byte signed prefix has a valid signature under key ID 2; SHA-1 of its `0x5cf0`-byte body matches the embedded digest. |

The script changes the outer TOC destination from zero to
`0x40306c00` and the final sector's 448-byte tail in a *memory copy* of
the saved eMMC span. Every check above still passes and produces the same
hashes. This proves the tested TOC field and tail are outside
these certificates and body digests. It does **not** prove that the unseen
secure monitor accepts the modified TOC; the monitor could inspect metadata
through another path. The visible `0x344fa` interface passes pointers to
the certificate sections, not the TOC base. The [secure-gate trace](bootrom-secure-gate-2026-11-07.md)
notes that the TOC pointer remains in a register and the secure handler is
not captured, so the absence of an explicit TOC argument is not proof of
acceptance.

## Initial SRAM-capacity gate and the selected-image special case

The first pass through `0x32a74` builds four descriptors: `KEYS`,
`PRIMAPP`, optional `R&D`, and the selected `MLO`. From the exact TOC,
their full lengths round to 5, 26, 0, and 49 sectors. A simple sum of
these full lengths is 80 sectors (40 KiB), seemingly too large for the
ROM's 64-sector SRAM loading window. That sum is **not** what the first
read requests. At `0x32aee`–`0x32af0`, when the loop index is 3, the ROM
replaces the selected descriptor's initial read count with **one sector**.
The comparison at `0x32af8` and callback at `0x32b06` use that replacement
count. The first pass therefore reads 5 + 26 + 1 = **32 sectors**, exactly
16 KiB; its write pointer ends at `0x40308000`, within the 32 KiB window.
The later read at `0x32b40`–`0x32b66` restores the selected descriptor's
full **49-sector** count (`0x32b40` loads the original count, not the
one-sector override). `analysis/bootrom/stack_tail_model.py` checks both
counts against the exact MLO TOC. The ROM calls secure services 0, optional
1, and 2 on the initial sections at `0x344fa`; it calls service 3 on the
selected full image only **after** the later storage read, at `0x32b7e`
through `0x344dc`. Thus the full copy is a pre-service-3 memory write.
The context word at `+8` that can skip these reads is initialized to zero
at `0x32e3a`; the raw MMC open path at `0x33af4` leaves that word zero.
Its raw-slot selector is in the separate card context, so retrying LBA 256
does not set the skip flag.

This distinction is essential to reachability. An earlier review of this
stage overlooked the one-sector override and wrongly concluded that the
initial capacity check rejects the exact MLO. The corrected trace shows
that this check permits it. It does not establish that this panel selects
the modeled MMC source or that the secure monitor accepts changed TOC
metadata.

## A writable sector tail in the selected MLO

`0x32a18` rounds the ISW section's `0x6040`-byte length up to 49 sectors,
or `0x6200` bytes. Its last 512-byte sector starts at relative MLO offset
`0xa000`. The signed ISW body ends at relative offset `0xa03f`; the
remaining 448 bytes at `0xa040..0xa1ff` are outside the MLO's TOC size,
`CertISW` certificate, and verified ISW body. In the saved eMMC image these
bytes lie at absolute offsets `0x2a040..0x2a1ff` and contain nonzero data.
Changing them would not alter any of the cryptographic checks above.

This matters because the ROM's full selected-image read uses the rounded
sector count. The range clamp at `0x34380` leaves an aligned destination
`0x40306c00` and length `0x6200` unchanged. The source-table entries for
MMC boot codes 5–7 point to `0x33bba`, whose callback advances the
destination by 512 bytes per sector. `0x36c62` passes each sector's
destination to `0x35f30`; the latter writes FIFO words to `[R1],#4`.
The MMC initializer `0x35d96`–`0x35d9e` sets the controller block-length
register to `0x200`; `0x35f3c` reads that length, and `0x35f78` loops for
that many FIFO words. This supports a 512-byte write per successful sector.
The final sector therefore targets `0x4030cc00..0x4030cdff`, putting the
448 bytes beyond the signed ISW body at `0x4030cc40..0x4030cdff`.
The destination crosses the ROM's `0x4030bfff` loading-window boundary.
The ROM itself uses `0x4030d000` for its stack and locations above it for
working state, confirming this overrun reaches its writable RAM workspace.

## Saved return address falls in the sector tail

`0x308d0` sets SP to `0x4030d000` before entering the boot loader. The
nested frame sizes visible in the ROM on the MMC path are:

| Function | Stack use | SP after entry |
| --- | ---: | ---: |
| `0x30a18` main | 16 | `0x4030cff0` |
| `0x30a7c` boot chooser | 64 | `0x4030cfb0` |
| `0x32dea` storage loader | 608 | `0x4030cd50` |
| `0x32a74` section loader | 168 | `0x4030cca8` |
| `0x33bba` MMC read callback | 48 | `0x4030cc78` |
| `0x36c62` sector reader | 32 | `0x4030cc58` |
| `0x35f30` FIFO copy | 20 | `0x4030cc44` |

The FIFO copy's `PUSH {R4-R7,LR}` saves LR at `0x4030cc54` and ends with
`POP {R4-R7,PC}`. That saved PC lies 20 bytes into the 448-byte sector tail
in the aligned-destination example. `analysis/bootrom/stack_tail_model.py`
reproduces the arithmetic and maps that word to MLO-relative offset
`0xa054` (eMMC user-area offset `0x2a054`). Among 512-byte-aligned destinations
inside the allowed SRAM window, `0x40306c00` is the sole address that places
the unsigned tail over this saved LR. If the edited TOC reaches this MMC callback,
and if the tail bytes are accepted from storage as modeled, the copy would
overwrite its own saved return address with bytes outside the signed MLO,
before the visible selected-image service-3 call.
This is a **strong static control-flow candidate**, not a reproduced ROM
exploit. The first-pass buffer check is satisfied by the selected-image
special case above. A separate [source-path trace](bootrom-source-path-2026-11-07.md)
finds that the exact installed MLO is at LBA 256, the second raw MMC slot
tried by the same callback on sources 5–7. The signed MLO's later boot path
proceeds to U-Boot only for inherited source code 5 or 6, both using that
callback. The source latch was not captured;
the secure monitor's treatment of modified TOC metadata remains the main
unresolved gate.

## What remains to establish

1. Capture or otherwise prove the ROM's selected storage source code on this
   unit. The exact MLO at raw MMC slot LBA 256 and the MLO's successful
   code-5-or-6 dispatcher strongly support callback `0x33bba`, but the
   source latch itself is absent from the recorded boot logs.
2. Determine whether the secure monitor performs a separate TOC destination
   validation. The public 48 KiB ROM image shows no such check before the
   flawed clamp; the secure-side SMC handler is not in this capture.
3. Determine whether the final sector callback completes on this unit with
   a modified destination; the visible MMC setup and FIFO loop specify 512
   bytes, but a live outcome has not been measured.
4. Keep any live trial separate from this analysis. Altering the eMMC TOC
   or adjacent sector could prevent boot; the current workspace scope
   authorizes investigation only.

Primary hardware references: [TI OMAP4460 TRM](https://www.ti.com/lit/ug/swpu235aa/swpu235aa.pdf)
and [TI's OMAP4460 register delta](https://www.ti.com/lit/pdf/swpu316),
which identifies the CH/speedup-disable fuse bit used by the other parser
lead. The certificate and callback conclusions above come from this unit's
captured ROM and saved firmware, not from another OMAP generation.
