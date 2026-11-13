# Offline OMAP4460 ROM-service audit, 2026-11-07

Scope: the exact CE9.9.0 package's signed PPA and MLO ISW, the existing ROM
USB/serial captures, the prior Linux ROM-read result, and public reference
material. **No Touch 10 connection or new device probe was used for this
audit.** This is a targeted trace of the plausible readback calls, not a
complete proof about every ROM routine.

## Inputs

- Exact package `firmware/codec-ce9.9.0/extracted/MLO`, SHA-256
  `2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427`.
  The extraction layout and IDA databases are described in
  `firmware/codec-ce9.9.0/analysis/README.md`.
- PPA IDA database `touch10-ce990-ppa.bin.i64`, loaded at `0x40300dd0`.
- MLO ISW IDA database `touch10-ce990-mlo-isw.bin.i64`, loaded at
  `0x40304350`.
- Existing USB PPA execution and four-byte length control are recorded in
  `ppa-memory-audit-2026-11-07.md`. The earlier live Linux result is in
  `rom-linux-read-2026-11-07.md`.

## PPA handoff and service calls

At `0x40303c2c`, the PPA installs its own service lookup routines at
`R9+0xc8` and `R9+0xcc`. At `0x40303c4c`, it copies pointers from low
addresses `0x402100` and `0x402104` to `R9+0xd0` and `R9+0xd4`. These
addresses are outside the extracted PPA image. The PPA does not show who
populates them. Its lookup at `0x40302c4c` invokes a callback obtained through
`[0x402104]` and, for fallback services, consults tables at `0x318100`,
`0x318140`, or `0x318200`. The actual implementations of those external
services are absent from this package.

| PPA site | Observed call and argument source | Readback assessment |
| --- | --- | --- |
| `0x40301ecc`–`0x40301ede` | Looks up service `0x77`, then calls it with `R0=R8` (destination), `R1=R10` (source), `R2=R11` (length). `R10` is `[R7+4]`, where `R7=[R9+0xd4]`; `R8=(R9-2251)&~1`. `R11` comes from internal PPA metadata. | Three arguments fit a copy/move operation during PPA memory cleanup. The observed source is a value from the external handoff table, not an address demonstrated to be set by the USB host. Nothing here sends copied bytes to USB or UART. The service's exact semantics remain unverified without its implementation. |
| `0x40303ba6`–`0x40303bc2` | Looks up service `0x1d` and calls it with `R0=R9+0xac` (four-byte output area), `R1=4`, `R2=[R7]`, `R3=[R7+4]-[R7]`, again with `R7=[R9+0xd4]`. | This processes a range from the same handoff table and returns a four-byte result. A checksum/hash interpretation is plausible but unproved. It is not an observed memory-export channel. |

The subtraction at `0x40301e7e` can underflow if the external end pointer is
below the cleanup destination. The length at `0x40303bbe` can similarly
underflow if the two external endpoints are reversed. Neither is a confirmed
vulnerability: no path was found from the editable USB `2ND` TOC or declared
length to those table values. The already completed four-byte outer-length
comparison produced identical cleanup numbers and the same fatal result.

## Signed MLO ISW

The HS signature path in function `0x40307864` reads a low entrypoint pointer
from `0x28400` or `0x30400`, then invokes selectors `0x0c` at `0x403078ec`
and `0x3e` at `0x4030794c`. The surrounding code reports certificate failure
for the first call and computes/checks a SHA-1 digest with the second. The
GP-device branch skips this check; the captured Touch 10 identifies as HS.
These are verification uses of ROM or boot handoff routines, not host-directed
reads of ROM contents.

The main ISW boot dispatcher at `0x40306644` selects MMC/SD1 boot code 5 or
eMMC boot code 6 and passes control to the storage loader. Its extracted code
has no identified USB or serial memory-export command. This is a targeted
call-path result; it does not establish the behavior of unexamined ROM code.

## Public binary check and consequence

[TI's public OMAP4460 TRM](https://www.ti.com.cn/cn/lit/pdf/swpu235) documents
the ROM boot architecture and USB peripheral boot. The
[TI OMAP4460 memory map](https://www.ti.com/jp/lit/pdf/swpu316)
places its 48 KiB Boot ROM at `0x40030000`–`0x4003bfff`. Those documents describe
the hardware; they are not a Boot ROM binary.

The checked [Zenofex SoC-BootROMs archive](https://github.com/Zenofex/SoC-BootROMs)
has only `ti/am335x.bootrom.bin` under its `ti/` tree at commit
`cacc2a6af00e29b8a67c83c128b3516487aa2eec`.
Targeted public searches did not yield a verified OMAP4460 ROM dump.
The OMAP4 `.2nd` files under `firmware/reference/omapboot/images/` are signed
second-stage images, not on-chip ROM dumps. This search does not prove that
no such dump exists elsewhere.

**Result:** the exact signed PPA/MLO reveals callable ROM/handoff services,
but no demonstrated arbitrary ROM-to-host readback path. The prior live
`/dev/mem` attempt targeted an OMAP4460 reserved region, caused an external
abort, and says nothing about the actual ROM's readability. The best next
offline step is to identify the semantics and
population of the `0x402100`/`0x402104` handoff table from a same-revision
OMAP4460 ROM binary or primary TI implementation material. Any new device
experiment should be designed from that evidence, rather than assuming
service `0x77` accepts a host-controlled ROM source pointer.
