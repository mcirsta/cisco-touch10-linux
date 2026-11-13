# Stock TWL6032 control-I2C read (2026-11-13)

## Scope and raw result

The owner authorized one upload and execution of the fixed four-register,
RAM-only reader. The exact 44,624-byte ARM ELF had SHA-256
`5fbf3dbd36f544b0c0e3eb191bcb02b8eb31c5106c72c79d66f0ec740f7ccbd0`.
The host checked stock Linux `3.4.113+`, the `twl6032` client at `1-0048`,
and 700 MHz CPU frequency. It verified the remote ELF's SHA-512 before
executing it once, then removed it from `/tmp` and verified its absence.

```text
offset_efuse,0xe0,0x5b
smps1_mpu_selector,0x55,0x00
smps2_core_selector,0x5b,0x00
smps5_iva_selector,0x49,0x00
```

These are **raw bytes from control I2C address `0x48`**, not verified live
SmartReflex voltage selectors. The names above were the helper's original
labels. The offset byte has bit 3 set, making the stock kernel's SMPS1
selector conversion use the 709 mV base when applied to a valid selector.
The zero selector bytes cannot be converted to rail voltages.

After cleanup, the stock kernel still ran at 700 MHz, and INA3221 at
`4-0041` reported bus voltages of 1000, 1216 and 976 mV with nonzero
currents. No PMIC value, persistent storage, boot setting or firmware was
written, and there was no reboot.

## Interpretation

The exact Cisco MLO and stock kernel use PMIC slave `0x12` for the OMAP
voltage controller. The Linux TWL core's PM_RECEIVER mapping instead
addresses the ordinary `0x48` I2C client. TI's
[TWL6032 EVM guide](https://www.ti.com/lit/ug/swcu105/swcu105.pdf)
documents separate general and SmartReflex I2C interfaces. The
[related TWL6030 datasheet](https://www.ti.com/lit/ds/symlink/twl6030.pdf)
states that SmartReflex registers are accessed through its SR-I2C interface
when SmartReflex is used. These sources and the live zero reads strongly
indicate that `0x48:0x55` is not a usable readback of the programmed
`0x12:0x55` selector. The exact TWL6032 register-access detail remains
unverified because its full data manual is not public here.

The ram111 observer used precisely that control-I2C mapping. It could
misreport the MPU rail as 0 V, so its source patch and DT node were removed
from the active series, and the built artifact was marked invalid. Ram111
was never booted on the panel. The last validated RAM fallback remains
ram110.

The [OMAP4460 TRM](../development/kernel/references/omap4460-swpu235ab.txt)
describes read-only `PRM_VP_MPU_VOLTAGE` at `0x4a307b64`, whose low byte is
the voltage processor's current programmed selector. Its usefulness on
this stock image depends on how the voltage processor was initialized;
this path is a candidate for a separate read-only check, not yet a rail
measurement.

Stock `/proc/kallsyms` locates `omap_vp_get_curr_volt` at `0xc002aa50`.
Offline decompilation shows that it reads the voltage processor's register
offset through the voltage-domain `read` callback, masks the selector, and
passes it to the PMIC's selector-to-microvolt callback. A direct stock
`/dev/mem` four-byte `read()` at `0x4a307b64` returned `Bad address`; the
stock system remained at Linux `3.4.113+` and 700 MHz afterward. The
subsequent authorized read-only `mmap()` helper succeeded; see the
[VP snapshot](perrier-omap-vp-stock-2026-11-13.md).
