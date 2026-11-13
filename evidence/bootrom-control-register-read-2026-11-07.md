# OMAP control-register gate: live read attempt

The ROM's configuration and CH handlers test bit 13 of physical register
`0x4a002220` through routine `0x317c6`. To determine its value, I used the
existing key-based root SSH session for read-only commands on 2026-11-07.

- `busybox devmem 0x4a002220 32` returned `devmem: applet not found`.
- `/dev/mem` exists as a root-readable character device.
- `dd if=/dev/mem bs=4 skip=310380680 count=1 | od -An -tx4` returned
  `dd: /dev/mem: Bad address`; `od` was also absent. The skip is the exact
  physical byte address divided by four, so the attempted read began at
  `0x4a002220`.

No value was obtained through Linux, and no device state was changed.
Subsequent offline analysis of the saved ROM USB GET_ID response resolved
the bit: ROM `0x317c6` places the bit-13 result in identity-response byte 6
bit 4, and the captured byte is `0x07`. Thus bit 13 is **0** (CH/speedup
enabled) on this unit. See
[`bootrom-usb-preauth-2026-11-07.md`](bootrom-usb-preauth-2026-11-07.md).
