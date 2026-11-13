# Ram111 SMPS1 observer: retired before device use

The offline-built ram111 image was **never transferred to or booted on the
Touch 10**. It has been invalidated and must not be used for a RAM trial.
The [2026-11-13 stock read](../../evidence/perrier-smps-selector-stock-2026-11-13.md)
returned `0x00` for `0x55`, `0x5b` and `0x49` through the TWL6032 control-I2C
client at `0x48`, despite powered rails. Ram111's `get_voltage` used the
same control-I2C path, so it could falsely report SMPS1 as 0 V. The active
kernel source overlay, DT node, binding compatible and generated patch
were removed. The original patch and review are retained under
[`retired/ram111`](retired/ram111/).

The `smps1-observe` artifact directory remains as a historical record.
Its `reviewed-image.json` now has `passed: false`, which makes the guarded
U-Boot runner reject it before connecting to the device. The ram111 build
and audit scripts also stop with an invalidation error. Ram110 remains the
last validated two-CPU RAM image and fallback.

The CE9.9.0 MLO and stock kernel identify TWL6032 SMPS1/VCORE1 as
the *intended software-controlled* MPU supply through voltage-controller
slave `0x12`. The later VP and INA cross-boot comparison identifies INA
channel 1 as MPU with high confidence, without electrically proving the
PCB net. See the [rail trace](../../evidence/perrier-mpu-rail-trace-2026-11-12.md),
[VP evidence](../../evidence/perrier-omap-vp-stock-2026-11-13.md) and
[power policy](power-policy.md).

The [stock VP snapshot](../../evidence/perrier-omap-vp-stock-2026-11-13.md)
successfully read `PRM_VP_MPU_VOLTAGE` and related registers through a
fixed read-only mapping. Its current requested MPU selector `0x18`
converts to 1.00018 V, matching one INA channel, while `VPENABLE=1` and
the initial/ON selector is `0x29`. A replacement observer should read the
OMAP VP path, not the PMIC control-I2C path, and must distinguish current
requested voltage from nominal and physical measured voltage. Any future
RAM image needs a fresh build, audit and explicit device scope
authorization; no CPUfreq or rail writes are enabled.
