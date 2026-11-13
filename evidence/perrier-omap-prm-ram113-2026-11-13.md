# OMAP4460 voltage-controller state in ram113

On 2026-11-13, the owner-approved U-Boot RAM session booted
`6.18.48-perrier-ram113` with both CPUs online. A hash-pinned helper
(SHA-256 `4579e0a1c39338f170d8fca2c08042f26584462f179cfc3e67af92f7751aa11d`)
read 31 allowlisted words from the `0x4a307000` PRM page through a read-only
mapping. It ran at 700 MHz, 350 MHz, and restored 700 MHz. The helper was
removed from tmpfs; no voltage command was issued. The [raw and decoded
captures](../development/runs/20261113T154136Z-ram113-prm-read/result.json)
are saved on the host. [The one-shot runner](../development/runs/20261113T154025Z-uboot-ram113-80df7d/result.json)
passed factory p8 readback, stock recovery, and ADC postflight.

| Register group | Stock Linux 3.4 | ram113 Linux 6.18 at 700 / 350 / restored 700 MHz |
| --- | --- | --- |
| `PRM_VOLTCTRL`, VC channel configuration | `0x300`, `0x1717` | Identical at all three stages |
| VC slave and voltage/command addresses | MPU `0x12:55/56`, CORE `0x12:5b/5c`, IVA `0x12:49/4a` | Identical at all three stages |
| MPU VC ON command | selector `0x29` | `0x29` throughout |
| CORE VC ON command | selector `0x23` | `0x23` throughout |
| IVA VC ON command | selector `0x36` | `0x15` throughout |
| MPU VP config and current selector | enabled, `0x17` ≈ 0.988 V | disabled, `0x29` throughout |
| CORE VP config and current selector | enabled, `0x15` ≈ 0.962 V | disabled, `0x23` throughout |
| IVA VP config and current selector | enabled, `0x2e` ≈ 1.279 V | disabled, `0x15` throughout |
| VC I2C mode and clock words | `0x8`, `0x0b00282c` | `0x0`, `0x00006026` throughout |
| Likely MPU INA channel 1 | about 0.992 V in an earlier stock sample | 1.208 / 1.200 / 1.208 V |
| Likely CORE INA channel 3 | about 0.960 V in an earlier stock sample | 1.128 V throughout |

The ram113 read confirms that changing the CPU M2 divider did **not** change
VP selectors or VC command words. This is a fixed-voltage boot policy. The
INA readings vary by one 8 mV step at 350 MHz, plausibly sensor quantization
or load droop, not a voltage command. The stock and RAM voltage snapshots
were taken in different boots and are not simultaneous rail measurements.

The `PRM_VC_VAL_BYPASS` register is at `0x4a307ba0`. The OMAP4460 TRM
(`development/kernel/references/omap4460-swpu235ab.txt`, Table 3-877) says
bit 24 `VALID` is automatically **cleared** after an acknowledge or error;
`1` means pending. Cisco MLO's helper at `0x403044e4` writes data/register/
slave fields, sets bit 24, then polls until that bit clears. Its OMAP4460
branch uses slave `0x12`, register `0x55` and selector `0x28` for SMPS1.
Mainline `omap_vc_bypass_scale()` has the same command packing but exits its
poll when `VALID` is set. A future Perrier voltage provider should not copy
that completion check without resolving this difference. A cleared bit alone
does not distinguish acknowledge from error, so any live transition must
also check the INA rail and restore the saved selector on a normal exit.

The live experiment did not program a PMIC or PRM register. The next stage
is a fixed-700-MHz, bounded MPU-only bypass test with preflight checks for
the exact inherited VC/VP state, a small downward selector step, INA
readback, and an immediate return to selector `0x29`. It should not enable
the generic `omap2_common_pm_late_init()` sequence, which would overwrite
the board's VC commands, VP limits, and I2C timings.

That subsequent [bounded VC test](../development/kernel/power/omap4-mpu-bypass-step.md)
passed twice, including once with both CPUs busy. The earlier read-only
comparison remains a baseline; the test's exact commands and recovery
records are in the linked note.
