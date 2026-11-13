# OMAP4460 Boot ROM static audit: stage 2

Scope: offline analysis of the Touch 10's 48 KiB ROM and the exact CE9.9.0
MLO. No commands were sent to the panel. Addresses are low ROM alias; add
`0x40000000` for the physical alias used for the dump. Stage 1 has the hashes
and working database details.

## Authenticated storage path

The relevant path is `0x30b66` -> `0x32dea` -> `0x32f40` -> `0x32a74` for
the non-type-3 image selected by the TOC. The ROM scans a maximum of 16
32-byte TOC entries at `0x34308`. `0x344ac` transfers the selected record's
`+0x00` offset, `+0x04` size, `+0x08` auxiliary word, and `+0x10`
destination word to the caller's descriptor. `0x32a18` converts the offset
and size to sector numbers and a payload pointer. The exact Cisco MLO has
MLO, PRIMAPP, and KEYS records, all with `+0x10 = 0`; the image is 41,024
bytes and the actual last byte of a section is at offset `0xa03f`.

`0x32a74` first reads up to four named sections into the internal SRAM
buffer. Its `0x32af2`-`0x32afc` comparison bounds each sector count against
the current SRAM write pointer, and the callback at `0x32b06` performs the
read. This is a distinct initial read from the later candidate-A read.
The fourth descriptor is the selected image, but `0x32aee`-`0x32af0`
overrides its first-pass count to **one sector**. On the exact MLO, the
first pass is therefore KEYS 5 + PRIMAPP 26 + selected MLO header 1 = 32
sectors (16 KiB), not the 80-sector sum of all full sections. The first
pass fits in the 64-sector internal window. The function then
checks a status halfword bit `0x400` at `0x32b24`. If it is clear, it calls
`0x344fa` with pointers to the named section payloads. That routine invokes
monitor services 0, 1 when an optional payload is present, and 2 via
`0x30f24`, `0x30f36`, and `0x30f48`; all route through `SMC #1` at
`0x375b0`. Service 2 returning nonzero reaches `0x34568`, which branches
through `0x300c0` to the self-loop at `0x300a8` on this type-2 unit.
On the success path, `0x34554`-`0x3455a` sets bit `0x400`.
The boot context status halfword is initialized to zero at `0x32e3c`, so
the first pass cannot skip this gate merely because of stale flag state.

Only after that gate does `0x32b40`-`0x32b66` load the selected section's
destination and **full** sector count (49 for the exact MLO), call the
flawed range clamp at `0x34380`, and invoke the storage-read callback.
`0x32b72` checks bit `0x400` again before proceeding. The loaded selected
image is then passed to monitor service 3 through `0x344dc` and `0x30f5a`
at `0x32b7e`. Thus the full storage copy follows an earlier KEYS/PPA
service gate but precedes the visible selected-image service. The gate's
shown arguments are section payload pointers, not the TOC base, but the
secure monitor handler is not visible in this dump and may apply further
checks. Whether a TOC-only edit
to `+0x10` preserves verification is **unresolved**. The prior
`ppa-memory-audit-2026-11-07.md` establishes that this TOC occupies the
outer `0x000..0x1ff` region while the key and PPA payloads begin at
`0x200`, which makes the TOC field a plausible unauthenticated input but
does not reveal the secure monitor's complete policy.

Stage 3 independently verifies all three certificate signatures and both
body hashes against the exact MLO and captured MPKH. Changing only TOC
`+0x10` leaves those cryptographic checks unchanged. The secure monitor's
possible independent structural validation remains unresolved. Stage 3 also
identifies 448 bytes outside the signed ISW body in the final sector and a
conditional path from those bytes to a saved return address. An intermediate
review incorrectly summed all four full sections and treated the first-pass
SRAM check as a blocker; the one-sector override above corrects that.

The boot-source callback table at `0x37660` contains three words per source.
For sources 5–7 its read callback is `0x33bba`. That callback obtains the
destination from descriptor word `+8`, then calls `0x36c62` for each sector.
`0x36c62` passes that destination to `0x35f30`, whose `0x35f74` instruction
stores successive FIFO words at `[R1],#4`. The MMC setup writes `0x200` to
the block-length register at `0x35d96`-`0x35d9e`, and the FIFO loop reads
that length at `0x35f3c`, supporting a 512-byte copy per sector. No second destination-window
check is visible in this callback chain. This supports the modeled write
effect once the secure gate is passed. The offline [source-path trace](bootrom-source-path-2026-11-07.md)
shows the exact MLO at the second raw MMC slot (LBA 256), which uses this
callback; the source-code latch itself has not been captured.

## Candidate A: incorrect bound on the full selected-image read

The flaw at `0x34380` is directly visible. For an address inside the SRAM
window `0x40304000..0x4030bfff`, it retains that address but limits length
against the full 32 KiB window instead of the remaining span. The offline
model now includes an aligned example: address `0x4030be00`, length
`0x2000` produces end `0x4030ddff`, 7,680 bytes past the window.
`0x32b4e` calls the clamp immediately before a storage read at `0x32b66`.
For the exact MLO section size `0x6040`, `0x32a18` computes 49 sectors
(`0x6200` bytes). A TOC destination of `0x40307e00` would preserve that
count through the clamp and end at `0x4030dfff`, 8 KiB beyond the window.
The ROM uses memory near `0x4030d000` for its stack and near `0x4030dc48`
for USB state, so the overrun reaches live ROM workspace if the gated read
occurs. This is an offline address calculation, not a live test.

To turn this into a ROM exploit on the HS Touch 10, all of the following
must hold: the image with modified destination metadata must be accepted by
the secure gate; the resulting read count must reach the callback as modeled;
the memory beyond the window must remain writable at this boot stage; and
the overwritten bytes must yield a controllable effect rather than a reset.
None of those four conditions has been reproduced. The existing valid MLO
uses destination zero, which the clamp redirects to the window base, so
normal boot does not trigger the overrun.

## Candidate B: TOC extent undercount in the peripheral path

`0x343e0` returns the end of the record with the largest *start* offset,
not the maximum of all record ends. `0x34406` uses this result as a transfer
span; the peripheral path calls it at `0x33038` after receiving the image.
The offline model demonstrates a 63,232-byte undercount for a deliberately
unsorted synthetic TOC. The exact MLO has no undercount. A follow-up
[caller audit](bootrom-other-leads-2026-11-07.md) found that the type-2
peripheral caller does not use the computed destination or span after this
call; it checks only the return code. The other visible caller takes a branch
that skips `0x343e0`. The incorrect extent therefore has **no established
effect** on either visible caller. Direct TOC-offset pointers elsewhere in
the peripheral path are a separate issue, not evidence that this undercount
is exploitable.

## Candidate C: image configuration before secure verification

`0x344fa` conditionally calls `0x36e74` on the selected image payload at
offset `+0xa4` **before** its SMC verification calls. The exact MLO contains
the expected `0x16793a22` header at file offset `0x40a4`. `0x36e74` copies a
fixed `0x110` bytes, then interprets up to 32 address/value pairs. Depending
on flag bits, it can store a word or halfword to an allowed address or poll
an address. The address filter at `0x36ebc..0x36efa` permits low addresses
`0x0002c000..0x3ffffffe` and several narrow MMIO windows; other addresses
are skipped. The bit-13 check of register `0x4a002220` at `0x317c6`
appears to disable this interpreter when set. A later
[read-only attempt](bootrom-control-register-read-2026-11-07.md) through
Linux `/dev/mem` returned `Bad address`, so the bit's value on this unit
and security/firewall behavior remain unknown.

The offline filter model in `analysis/bootrom/config_allowlist_model.py`
classifies all ten nonzero entries in the exact Cisco MLO table as denied:
they target `0x480049xx` and `0x48004dxx`, outside the ROM filter. An
artificial entry at `0x4a004100` would pass the address test, whereas
`0x4030d000` would not. This narrows the finding: the installed table does
not itself cause a pre-verification register write in this interpreter.
The model says nothing about the fuse bit or whether an allowed register is
writable from the ROM's current privilege state.

This is a deliberate pre-verification configuration mechanism, not by
itself a vulnerability. It is a higher-priority attack surface than the
ordinary USB descriptor handler because an attacker-controlled image may
reach address/value interpretation before authentication, subject to the
fuse gate and allowlist. Next work is to model that allowlist exactly,
identify the permitted registers, and determine whether any write can alter
the secure monitor's state or boot decision. No such effect has been shown.

## Peripheral USB limit and trust boundary

`0x33092` asks the transport for a four-byte image length and then checks it
at `0x33258`-`0x3325e` against `0x4030bfff - 0x40304000` on this type-2
unit. The largest accepted declared length is 32,767 bytes. The 41,024-byte
exact MLO therefore cannot be sent unchanged as one image through this ROM
USB state machine. Its earlier USB responses match the boundary: 31,744
bytes accepted at transport level, 32,768 rejected. Passing the transport
check does not mean the secure monitor accepts or executes an image.

The USB setup handler at `0x35900` caps descriptor replies to `wLength`.
The receive-completion count narrowing at `0x35520` is still under review
for alternate callers; the generic image receive above is bounded below
64 KiB. These are observations about this path, not a full USB-controller
audit.

The standard setup dispatcher at `0x35a00` handles IN requests 0, 6, 8,
and 10 and OUT requests 1, 3, 5, 9, and 11; other request numbers take the
stall path. String-index lookup at `0x358aa` checks three four-entry ranges
before selecting a fixed descriptor table. No unbounded host-selected table
index was found in this first pass. Endpoint state transitions and the
receive-completion count still need a separate path-by-path review.

## Additional parser lead

The optional CH path in `0x32fd6` calls `0x32f74` when the TOC contains a
recognized CHSETTINGS entry. `0x32f74` builds pointers from four TOC offsets,
and `0x34774` probes those targets for CH record magics. The 0..15 TOC index
is bounded by `0x34308`; the section offsets themselves have not yet been
traced to a bound against the received image before these dereferences.
This is a **hypothesis for an out-of-buffer read**, with no evidence of data
exfiltration or code execution. The CH command handlers and ROM-config
policy need separate review.

## Current ranking

| Lead | Path | Established fact | Main missing proof |
| --- | --- | --- | --- |
| A: SRAM range clamp | Storage boot | Wrong remaining-length calculation; the 5+26+1-sector first pass fits; exact certificate chain remains valid after a TOC-only edit; the later full read has 448 unsigned tail bytes and a modeled saved-PC overlap. The exact MLO at raw MMC slot LBA 256 strongly supports the callback. | Does the secure monitor separately reject the edited TOC, and would the modified read complete? |
| C: configuration interpreter | Storage image before SMC | Fixed table is interpreted before verification when a fuse gate permits; address filter is mapped. | Is the interpreter enabled on this unit, and can any permitted write change a security-relevant state? |
| CH offsets | Peripheral boot | TOC offsets form pointers dereferenced by CH parser. | Are they bounded elsewhere, and what can an out-of-buffer target affect? |
| USB count narrowing | USB completion | The completion count is narrowed to 16 bits. | Can a reachable caller request at least 64 KiB? The normal image path cannot. |
| B: TOC extent | Peripheral boot | Max-start record can undercount the full image extent, but the visible type-2 caller discards that computed span and type 3 skips the routine. | No security effect shown on either visible caller; deprioritized. |

No lead is yet a reproduced signature bypass, ROM code execution, or ROM
data-exfiltration vulnerability on the Touch 10.

## Priority for the next stage

1. Determine whether the pre-verification configuration interpreter is
   enabled on this unit and map its allowed register effects.
2. Trace the secure monitor service ABI and determine whether TOC `+0x10`
   is covered by verification or validated elsewhere. A read-only capture
   of secure-side memory, if accessible, would resolve the biggest unknown.
3. Confirm the exact boot source and SRAM permissions using existing
   evidence; the storage callback's destination semantics are traced above.
4. Complete the USB setup and CH parser input-to-sink table, including
   short-transfer and integer-wrap paths. Rank each finding by reachable
   effect on this HS device.
5. Keep any proposed hardware probe separate from this offline report. A
   device test should have a single changed variable, expected result, and
   recovery route before it is run.
