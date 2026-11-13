# OMAP4460 ROM configuration-header parser: exact USB path

Scope: offline disassembly of this Touch 10's captured 48 KiB ROM, mapped
at low alias `0x30000..0x3bfff`. No panel command, upload, or storage change
was made. Addresses below use that low alias.

## Input to the CH handler

After a complete peripheral image receive, `0x332b6` calls `0x32fd6`
before the later image-security path. `0x32fd6` scans the first 512-byte
TOC with `0x34308`, which recognizes at most sixteen 32-byte entries and
stores each recognized name's ordinal in a fourteen-byte map. ROM name
indices 10, 11, 12, and 13 are `CHSETTINGS`, `CHRAM`, `CHFLASH`, and
`CHMMCSD`. If map byte 10 is not `0xff`, `0x32ff0..0x33002` calls
`0x32f74` and then advances the image pointer by `0x200` before scanning
the next TOC. This makes a CH-labeled first sector reachable from the USB
image before the signed-image services.

`0x32f74` copies map bytes 10–13 and, for each non-`0xff` ordinal, reads
the entry's 32-bit offset at `image_base + ordinal*32` (`0x32fa0..0x32faa`).
It adds the image base to that offset at `0x32fac` and places the resulting
pointer in a four-element local array. The ordinal is bounded to 0–15 by
the TOC scanner, but **the 32-bit section offset is not compared with the
received image length** in this path. The addition is 32-bit arithmetic,
so a crafted offset can point outside the received image or wrap around
the address space. A target outside mapped/readable memory may fault when
the handler probes it; no data-export path follows from that observation.

The four pointers enter `0x34774` in this order: `CHSETTINGS` in R3,
`CHRAM` as its first stack argument, `CHFLASH` as its second, and
`CHMMCSD` as its third. `0x32f74` always returns zero at `0x32fd0`,
discarding the handler's status. A rejected or absent CH therefore does
not itself decide image acceptance; `0x32fd6` continues to the second TOC.

## Gate and per-record checks

`0x34788` calls `0x317c6`, which reads bit 13 of `0x4a002220`.
If the bit is one, `0x3478e` takes the failure return before probing any
CH pointer. TI labels this bit `STD_FUSE_CH_SPEEDUP_DISABLE` in its
[OMAP4460 register delta](https://www.ti.com/lit/pdf/swpu316).
The prior read-only Linux `/dev/mem` attempt returned `Bad address`, but
the saved ROM GET_ID response resolves this bit. The ROM places the
`0x317c6` result in response byte 6 bit 4; captured byte 6 is `0x07`, so
bit 13 is **0** and CH processing passes this fuse gate. See
[`bootrom-usb-preauth-2026-11-07.md`](bootrom-usb-preauth-2026-11-07.md).

If the fuse permits CH processing, each nonnull pointer is first read by
`0x37380`, a four-byte little-endian load using `LDRB` at pointer offsets
0–3. The handler compares that word with a record magic and then checks
the valid byte at pointer `+4` before calling its sub-handler:

| Record | ROM branch | Required magic | Sub-handler and visible effect |
| --- | --- | --- | --- |
| `CHSETTINGS` | `0x347c0..0x347ee` | `0xc0c0c0c1` | `0x30c44`, called with record `+8`. It interprets fixed configuration fields and calls fixed ROM clock/memory setup helpers; this is a real pre-authentication configuration path when enabled. |
| `CHRAM` | `0x34790..0x347bc` | `0xc0c0c0c2` | `0x32346`, called with record `+8`; its visible writes include fixed controller addresses `0x4e000040` and `0x482af040`, plus memory setup helpers. |
| `CHFLASH` | `0x347f2..0x34824` | `0xc0c0c0c3` | `0x30566`, called with record `+8`; it writes configuration registers in the `0x50000000` block. Its call to `0x304fc` uses `R1=0`, fixing that helper's register block offset on this path. |
| `CHMMCSD` | `0x34828..0x348b4` | `0xc0c0c0c4` | **Skipped on this USB CH route.** `0x32fc8` ORs bit 8 (`0x100`) into the flags passed to `0x34774`; `0x3482e..0x34830` skips the MMC branch when that bit is set. The branch's bounded callback selection and indirect call are not reached through `0x32f74`. |

The other three branches are also skipped if their corresponding flag bit
is set (bit 5 for `CHSETTINGS`, bit 6 for `CHRAM`, bit 7 for `CHFLASH`).
Their status can set a context byte and emit a ROM trace event, but the
wrapper discards the handler return. The first pointer read and magic
comparison happen **before** a signed image is authenticated. A valid CH
record in the received buffer can configure hardware by design; this
audit does not identify an unrestricted memory-write primitive from an
out-of-buffer offset.

## Assessment

The missing section-offset bound is a **confirmed pre-authentication
out-of-received-image read candidate**, with the fuse gate enabled on this unit.
It can select a four-byte magic probe at a chosen address, and a matching
valid record may trigger one of three fixed-purpose configuration handlers.
No arbitrary data readback, general memory write, or signature bypass is
demonstrated. The original CHMMCSD lead is narrower than previously
described: its handler is unreachable from this USB CH wrapper because
bit 8 is forced on. The effect of an out-of-buffer magic match on this unit
has not been tested. This lead still ranks below the
storage-path range-clamp candidate.
