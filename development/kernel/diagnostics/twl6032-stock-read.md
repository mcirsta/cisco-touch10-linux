# Stock-kernel TWL6032 selector read

**Historical diagnostic only:** this helper's voltage-offset bytes came
from control I2C `0x48` and cannot be treated as live SmartReflex selectors.
Do not rerun it to infer rail voltage.

The [fixed-register reader](twl6032_stock_read.c) uses the stock kernel's
`/dev/i2c-1` interface. It makes exactly four combined I2C transactions to
the already enumerated TWL6032 at 7-bit address `0x48`. Each transaction
sends a one-byte register index, then reads one byte. The fixed indices are
`0xe0` (SMPS offset EPROM), `0x55` (SMPS1), `0x5b` (SMPS2), and `0x49`
(SMPS5). There is no command-line input, arbitrary bus scan, register-value
write, firmware operation, clock change, or reboot.

This was intended to resolve the disagreement between [stock OPP voltages](../../../evidence/perrier-stock-opp-2026-11-12.md)
and [INA3221 load response](../../../evidence/perrier-ina-arithmetic-2026-11-12.md).
The stock board's I2C table has no INA channel labels, and stock regulator
sysfs exposes no VCORE1 voltage.

The source was built with the existing static ARMv7 musl toolchain using
`-static -Os -Wall -Wextra -Werror`. The ELF is 44 KiB and statically
linked. A QEMU execution checked that it stops cleanly when `/dev/i2c-1`
is absent. With one-time authorization, it was copied to RAM-only `/tmp`,
hash-verified, run once on stock Linux, and removed on 2026-11-13.
The [raw result and interpretation](../../../evidence/perrier-smps-selector-stock-2026-11-13.md)
are recorded separately.

| Artifact | SHA-256 | SHA-512 |
| --- | --- | --- |
| `twl6032_stock_read.arm` | `5fbf3dbd36f544b0c0e3eb191bcb02b8eb31c5106c72c79d66f0ec740f7ccbd0` | `f53e4293d79c6313fecdcb8a66175da9f45234e9163bd4d15b269b976dac38130277b889cfbfaf8ec74aea9ac289a072a83fc42275e4c591455a35d9667a83e2` |

The bounded sequence confirmed stock Linux and `1-0048`, copied this exact
ELF to `/tmp`, verified its SHA-512 with stock BusyBox, executed it once,
recorded the four raw bytes and INA readings on the PC, removed the ELF,
and confirmed stock Linux was still running. It needed no U-Boot
environment write or display reset.

The stock kernel's `twl6030_vsel_to_uv` uses offset EPROM bit 3 for the
SMPS1 conversion: selectors 1–57 map to `709000 + (selector-1)*12660`
microvolts when set, or `607700 + (selector-1)*12660` when clear; selector
58 maps to 1.35 V. The helper read `0x5b` at `0xe0`, so bit 3 is set, but
it read `0x00` at the three voltage offsets on **control I2C `0x48`**.
Those zero bytes do not represent powered-rail voltages. The OMAP voltage
controller uses slave `0x12` on the separate SmartReflex interface; this
helper does not read that interface. Do not use it to assign an INA channel.
