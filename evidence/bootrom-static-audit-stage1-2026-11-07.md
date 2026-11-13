# OMAP4460 Boot ROM static audit: stage 1

Source image: `omap4460-bootrom-2026-11-07.bin`, 49,152 bytes, SHA-256
`7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff`.
No panel commands or mutations were used during this static analysis. The
working IDA database is `analysis/bootrom/omap4460-bootrom-lowalias.bin.i64`.
All addresses below are **low ROM alias** addresses; add `0x40000000` for the
Linux physical mapping used to capture the image.

## Binary map and disassembly setup

- The reset vector at `0x30000` is ARM `B 0x30910`. At `0x30910`, the reset
  path reads the chip status/control register at `0x4a0022c4`, sets up the
  stack at `0x4030d000`, and continues into ROM initialization.
- This image contains mixed ARM and Thumb-2 code. A raw IDA import defaults
  to a 64-bit ARM segment and gives false disassembly; the segment must be
  set to 32-bit and Thumb mode set at Thumb entry points. Provisional function
  discovery is therefore not a claim of exhaustive code coverage.
- Internal pointer tables use addresses near `0x00030000`, not the
  `0x40030000` physical mapping. The IDA working copy is loaded at the low
  alias so those pointers resolve. It is byte-identical to the captured image.
- The table at `0x37b84` points to image/section names at `0x3802d`–`0x3807b`,
  including `2ND`, `MLO`, `ULO`, `PRIMAPP`, `KEYS`, and `ISSW`.
- The image includes USB controller accesses at `0x4a0ab000` and ROM work
  buffers around `0x4030dbec`–`0x4030dc48`. ARM `SMC #0` instructions occur
  at `0x30134`, `0x3013c`, `0x309c8`, and `0x34f88`; the effects of their
  secure-side handlers are not established by this 48 KiB image alone.

## Input paths located

| Low alias address | Observed behavior | Audit status |
| --- | --- | --- |
| `0x348bc` | Builds the ASIC identity response used by ROM host discovery; writes version and identity fields to its output structure. | Entry/output identified; no vulnerability claim. |
| `0x35b8a` | USB interrupt dispatch based on controller status; routes endpoint events to transmit, receive, and setup handlers. | Main USB interrupt path identified. |
| `0x35900` | USB GET_DESCRIPTOR handler selects among fixed descriptors and caps response length to host `wLength` at `0x359c2`–`0x359ca`. | The requested length is capped in this handler. |
| `0x3541a` | Copies a specified byte count from USB FIFO to RAM, using word and byte tails. | Caller-provided destination and count need tracing. |
| `0x354dc` | USB receive completion compares transferred bytes with requested bytes, then invokes `0x3541a`. It narrows a count to 16 bits at `0x35520`. | Possible arithmetic concern; generic boot receive in `0x33092` limits its request below 64 KiB. Other callers remain to be checked. |
| `0x33092` | Peripheral boot state machine first requests four bytes, then checks the declared transfer length against `0x4030bfff - destination` at `0x33258`–`0x3325e` before requesting the body. For the non-type-3 path used by this HS unit, destination is `0x40304000`, making the largest accepted declared length 32,767 bytes. | This explains the captured 31,744-byte acceptance and 32,768-byte rejection. The 41,024-byte MLO cannot pass unchanged through this one-image USB receive path. |
| `0x34308` | Scans up to 16 TOC records of 32 bytes, matching names against the ROM name table. Recognized indices are stored in a 14-byte output map. | The record count is bounded. Caller must provide the full 512-byte TOC. |
| `0x344ac` | Copies fields from TOC entry `base + index * 32` without a local index check. | Known callers obtain indices from `0x34308` or test for `0xff`; no out-of-range input demonstrated. |

## Candidate A: range clamp uses the window base

At `0x34380`, the ROM classifies a requested destination into an allowed
window. For internal SRAM it uses `0x40304000`–`0x4030bfff`. If the requested
address is already inside the window, it leaves that address unchanged, but
at `0x343c4`–`0x343d2` it computes/clamps the length against
`upper - lower + 1` (32 KiB), **not** `upper - requested_address + 1`.
Consequently a request with destination `0x4030be00` and length `0x2000`
remains unchanged, although it ends at `0x4030ddff`, `0x1e00` bytes beyond
the window. The model in `analysis/bootrom/rom_range_model.py` reproduces the
observed unsigned branches and this arithmetic. `0x4030be00` is also
512-byte aligned, so this example does not rely on an unaligned destination.

This clamp is called at `0x32b4e` before a storage read callback in
`0x32a74`. The path is selected from `0x32dea` at `0x32f40` when the chosen
TOC-name index is nonzero; `MLO` has index 4 in the ROM name table. The
selected record's word at offset `+0x10` is copied into the destination
descriptor by `0x344ac` and `0x32a18`. The exact Cisco MLO sets this word to
zero, which the clamp redirects to the SRAM window base. A modified TOC can
set it near the window end. The read callback's behavior and authentication
coverage still need to be confirmed end to end. Follow-up disassembly found
that `0x32b38` invokes secure verification before this read, and a failed
verification reaches a fatal loop at `0x300a8`. The shown secure-service
arguments are section payload pointers rather than a TOC pointer, but the
secure handler is not visible in this dump. This is a **high-priority bounds
flaw with unproven reachability on the HS device**, not a demonstrated
exploit. See stage 2 for the gate trace. No boot storage was modified or test
image submitted.

## Candidate B: image extent follows largest start offset

`0x343e0` computes an image extent by scanning up to 16 TOC records. It
updates its result only when the current record's **start offset** exceeds
the largest start offset so far (`0x343ea`–`0x343f2`). The returned value is
then that record's `start + size`. For records `(start=0x1000,size=0x100)`
and `(start=0x800,size=0x10000)`, it would return `0x1100`, although the
second record ends at `0x10800`. `0x34406` calls this routine and passes the
result to the transfer-range clamp at `0x34380`; `0x32cec` and `0x32fd6`
call `0x34406`.

`analysis/bootrom/toc_extent_model.py` reproduces the undercount for this
synthetic TOC. On the exact installed MLO, it returns `0xa040`, equal to the
actual maximum section end, so the authentic image does not exhibit the
condition.

This is a **statically demonstrated undercount for unsorted extents**, not a
confirmed security vulnerability. The remaining questions are whether this
TOC ordering is reachable from the USB route before authentication, whether
another check rejects it, and whether a later consumer reads beyond the
received buffer or merely rejects the image.

## Trust-boundary limits

The exact installed MLO is signed and its root-key record matches the
captured ROM MPKH. The ROM USB tests previously showed that raw unsigned
bytes were received at the transport level but did not execute. This stage
has **not** identified a signature bypass or a host-directed arbitrary memory
read/write command. The SMC calls and signed PPA/MLO stages require a separate
trace before any claim about the complete secure verification path.

The non-type-3 path eventually reaches `0x346ec` and `0x34686`, which arrange
a callback to the ARM `SMC #0` veneer at `0x34f80` and call monitor-service
wrappers through `0x30f16` and `SMC #1` at `0x375f8`. The service selectors
are visible; their secure-side implementation and final acceptance rules are
not established by the public 48 KiB dump alone.

## Next stage

1. Trace the generic peripheral callbacks in `0x33092` to the USB endpoint
   implementation and account for every host-controlled length and pointer.
2. Trace the `0x343e0` undercount through the signed-image path, including
   checks made by the PPA and MLO, and build an offline model for malformed
   record order/size.
3. Map the SMC call arguments and return values, then distinguish code
   present in this dump from secure-side implementations not visible here.
4. Review all USB setup request handlers and DMA completion arithmetic for
   bounds, zero-length, short-transfer, and state-transition behavior.

Primary hardware reference: [TI OMAP4460 TRM](https://www.ti.com/lit/ug/swpu235aa/swpu235aa.pdf).
