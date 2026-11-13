# OMAP4460 ROM range clamp callers and peripheral reachability

Scope: offline disassembly of the captured Touch 10 ROM. No panel command
or device change. All addresses use the ROM's low alias.

The range clamp at `0x34380` has two direct code callers: `0x32b4e` and
`0x3446c`. IDA has no data reference to it, and no literal `0x34380` or
Thumb `0x34381` pointer occurs in the 48 KiB ROM. This does not rule out
an unrecognized computed call, but the visible caller set is small.

| Caller | Input and subsequent use | Result |
| --- | --- | --- |
| `0x32b4e` in `0x32a74` | Selected storage-image TOC `+0x10` becomes destination; full selected sector count becomes length. `0x32b66` passes the clamped pair to the MMC read callback. | This is the stack-overwrite candidate. It requires a modified boot image on a storage source and passage through secure services 0–2. |
| `0x3446c` in `0x34406` | A recognized TOC destination and computed image extent are stored to caller-provided outputs, then clamped. `0x34406` also sets a selected-name bit. | On the type-2 peripheral caller `0x33038`, the destination/extent outputs land in local stack slots that are not subsequently read. Only the return code and selected-name bit matter. No transfer uses this clamped pair. |

The other caller of `0x34406` is `0x32d08` in `0x32cec`. The storage
loader reaches that routine only on the type-3 branch at `0x32efe`–
`0x32f0c`. For type 3, `0x34406` takes `0x34424`–`0x3443a` and skips the
clamp at `0x3446c`. It therefore does not supply another clamp-driven
write on this type-2 HS panel.

The peripheral chooser sends source codes `A`–`G` through common receiver
`0x33092` (`0x30b6c`–`0x30b8a`), including the tested USB path. On type 2,
the actual receive destination is fixed at `0x40304000` (`0x330dc`–
`0x330e0`). Before asking the transport for the image body, `0x33258`–
`0x3325e` checks the host-declared length against
`0x4030bfff - 0x40304000 = 0x7fff`, allowing at most 32,767 bytes.
That transfer does not take its destination from TOC `+0x10`.

After reception, `0x332b6` calls `0x32fd6`; its type-2 path can call
`0x34406`/`0x34380` while inspecting the TOC, but discards the adjusted
address and extent before `0x346ec` starts the image-security path.
The nonzero-name branch `0x34572` derives section pointers from TOC
offsets and calls secure services 0–3; it does not perform a storage copy
through the clamped destination. The visible USB/UART path therefore
cannot directly reproduce the `0x32b4e` arithmetic-to-copy chain.

A narrower **RAM-only gate experiment** is conceivable for a future
authorized test: use the previously exercised compact signed `2ND`/PPA
peripheral image (16,284 bytes) with only its outer TOC destination word
changed, and compare whether the same PPA banner still appears. That path
invokes the same service-0/2 wrappers but not the storage read. A positive
result would show that this peripheral invocation tolerates the edited
word; it would **not** prove that the raw MMC path accepts it or that the
stack-overwrite copy is reachable. No such new image was sent here.
