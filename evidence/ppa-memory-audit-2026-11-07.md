# Exact CE9.9.0 PPA memory-path audit

Input: `firmware/codec-ce9.9.0/extracted/MLO`, PPA bytes at file offsets
`0xdd0`–`0x3f9b`, loaded at `0x40300dd0`; IDA database in
`firmware/codec-ce9.9.0/analysis/touch10-ce990-ppa.bin.i64`.

The host controls the 32-bit USB BOOT length and unsigned outer TOC at file
offsets `0x000`–`0x1ff`. The root-key and PPA certificate/image bytes from
`0x200` onward are signed. The tested `2ND` format transferred the exact
signed PPA but no Cisco ISW stage. It printed the usual PPA banner and memory
cleanup messages, then a generic fatal message. A normal boot proceeds to
the Cisco MLO banner after those cleanup messages.

## Candidate arithmetic conditions

- At `0x40301e7e`–`0x40301e86`, PPA computes `R5 = R10 - R8`, where
  `R10 = *(R7 + 4)`, `R7 = *(R9 + 0xd4)`, and
  `R8 = (R9 - 2251) & ~1`. It checks `R5 >= 8` using the *unsigned* `BCS`
  branch. If `R10 < R8`, subtraction wraps and the resulting large value
  flows into the cleanup allocator's size calculation at
  `0x40301eea`–`0x40301ef6`. The preceding ROM copy service call uses a
  separate length (`R11`), so it is not made large by this subtraction.
  This is a conditional underflow candidate,
  not a demonstrated vulnerability: `R7` is taken through a table pointer
  stored at `0x402104`, outside this PPA image. The PPA code does not show
  who initializes that pointer, and we have not shown that USB input changes
  `R10` or `R8`.
- At `0x40303bba`–`0x40303bc2`, PPA passes `v3[1] - v3[0]` as a length to
  ROM service 29, again without a local lower-bound check. Both endpoints
  come from that external table. The service behavior and host control of
  these values are unproven.
- Service lookup at `0x403033f0` multiplies an index by eight, but its
  table bounds are initialized from signed PPA table addresses in
  `0x40303bd8`. No host-controlled count has been identified.
- The PPA print formatter at `0x40301f98` uses a 64-byte stack buffer and
  flushes at 60 bytes. Its observed format strings are PPA literals. No
  USB-controlled format string has been identified.

PPA registers its generic fatal printer (`0x403017f4`) through the external
table pointer in `0x40301880`. A call through that callback can therefore print
`FATAL ERROR` without leaving a direct call site or reason in this PPA image.
The fatal message alone does not identify an overwrite.

## Input-control check

The original compact candidate was 16,284 bytes, SHA-256
`6179320282c5d640853fd184db3052ada1650ab34de5f9cb21638de85052630d`.
The controlled 16,288-byte candidate was SHA-256
`5e7edc35f013febf0ad942d0293b17f1f145667e6dda1fe44c57b6740cf60fdb`.
Within their common prefix, only byte `0x4` differed: the `2ND` item size
changed from `0x339c` to `0x33a0`; the appended four bytes were existing
zero padding. The `PRIMAPP` size and all signed bytes were unchanged. Both
transfers completed and produced identical PPA free-space numbers, 2172 and
2252. Thus this four-byte outer-span change did not control the cleanup
boundary. USB and serial logs are
`rom-exact-ppa-2nd-20261107T013700Z-*` and
`rom-exact-ppa-2nd-plus4-20261107T015717Z-*` in this directory.

Next useful work is to identify what populates the external table's
range and free pointer, or obtain the OMAP4460 ROM code for direct parser
analysis. More extreme length values should not be treated as proof of a PPA
bug without first establishing this input path.

## Later selected-pointer control

A separately authorized [ROM USB pass run](bootrom-speedup-poll-2026-11-07/README.md)
changed the unsigned selected `2ND` TOC item to start at `0`, size `0x200`,
and placed a read-only speedup table in its outer header. The signed KEYS
and PPA region remained identical. The PPA still printed **2172 bytes** free,
**2252 bytes** to free, then the same fatal message. This is a much larger
selected-start/size change than the earlier four-byte size comparison, yet
it did not change those allocator values. It is evidence against deriving
the PPA cleanup range directly from the selected TOC item's start or size;
it does not resolve the external table's origin or rule out other PPA inputs.
