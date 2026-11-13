# Fixed OMAP4 voltage-processor stock read

The [reader](omap4_vp_stock_read.c) maps exactly one 4 KiB PRM page at
physical `0x4a307000` through stock `/dev/mem`, with `O_RDONLY` and
`PROT_READ`. It reads five fixed 32-bit registers and exits:

| Register | Physical address | Meaning |
| --- | --- | --- |
| `PRM_VP_CORE_VOLTAGE` | `0x4a307b4c` | CORE VP programmed selector, low byte |
| `PRM_VP_MPU_CONFIG` | `0x4a307b58` | MPU VP enable/init state |
| `PRM_VP_MPU_VOLTAGE` | `0x4a307b64` | MPU VP programmed selector, low byte |
| `PRM_VP_IVA_VOLTAGE` | `0x4a307b7c` | IVA VP programmed selector, low byte |
| `PRM_VC_VAL_CMD_VDD_MPU_L` | `0x4a307b98` | OMAP's configured MPU voltage command values |

The addresses and bit meanings come from the local
[OMAP4460 TRM](../../kernel/references/omap4460-swpu235ab.txt), tables
3-835, 3-841, 3-847, 3-857 and 3-873. The stock kernel's
`omap_vp_get_curr_volt` at `0xc002aa50` reads the voltage processor's
selector and converts it through its PMIC callback. The helper prints raw
words only; it neither claims a physical voltage measurement nor infers
that a zero word means a rail is off.

The source has no command-line parameters, register writes, `PROT_WRITE`,
or `O_RDWR`. It cannot change a PMIC selector or boot setting. A direct
four-byte `read()` of the MPU address returned `Bad address`, but the
one-time read-only `mmap()` run succeeded on the stock panel. The
[raw result](../../../evidence/perrier-omap-vp-stock-2026-11-13.md) is saved.

The static ARM ELF was built with the existing armv7 musl GCC using
`-static -Os -Wall -Wextra -Werror`. QEMU user-mode `-strace` verified
that, with no `/dev/mem`, it attempts only an `O_RDONLY` open, reports the
failure, and exits. No device was involved in that check.

| Artifact | SHA-256 | SHA-512 |
| --- | --- | --- |
| `omap4_vp_stock_read.arm` | `89a70e67a569fac941be6dffe44ed3a014d9b30c2a4a198d36ade235891b9c00` | `4c508dba1fe58c0dcd1a48b490f312ed9e20f444be8e993cc4c82000e2c7cb138f701fa2828e1b6b3ad1d78442028e117fe645602d65f9636605ee0e7256624c` |

The owner authorized one temporary `/tmp` upload and execution. The
helper's SHA-512 matched on the panel, it ran once, and it was removed.
The stock kernel remained healthy. That authorization is exhausted; any
new run would require a separate scope change. The reported values are
programmed requests, not physical voltage measurements.
