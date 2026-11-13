# Touch 10 temperature support (ram58)

The board has two identified temperature sources:

| Source | Stock evidence | Linux 6.18.48 interface |
| --- | --- | --- |
| TMP102 board sensor | `omap_i2c.3` at address `0x48`; stock `temp1_input` about 43.8 °C | Mainline `tmp102` hwmon `temp1_input` |
| OMAP4460 MPU bandgap | Described by the OMAP4460 SoC; stock does not expose it as a thermal zone | Mainline `ti-soc-thermal` `cpu_thermal/temp` |

The two stock INA3221 monitors expose power measurements, not temperature.
OMAP4460 has one on-chip bandgap sensor in its mainline data, for the MPU;
the stock GPU governor does not imply a separate GPU temperature sensor.

`omap4-perrier-thermal.dts` adds the TMP102 to the established I²C3 bus and
the on-chip bandgap plus its GPIO86 TSHUT *input*. The stock pinmux list and
GPIO ownership list show no board use of GPIO86. GPIO3 is instantiated alone
with `ti,no-reset-on-init`; the generic `/ocp` remains disabled. The CPU zone
keeps mainline alert and critical trips but drops its cpufreq cooling map,
because CPU frequency scaling remains disabled in the temporary image. No
voltage, pinmux, panel power, or boot-storage setting was added. The TMP102
driver sets a volatile conversion configuration, and the bandgap driver sets
on-chip thermal thresholds during probe.

The Qt program scans sysfs for `cpu_thermal` and `tmp102`, displays CPU and
Board values in Celsius, and refreshes every two seconds. Missing sensors
show `unavailable`.

Build and audit:

```sh
cmake --build development/perrier-qt/build-arm-a9-local
python3 development/perrier-qt/stage_runtime.py
python3 development/perrier-qt/preflight_qemu.py
python3 development/perrier-ramenv/build_image.py --profile native-thermal
python3 development/perrier-thermal/audit_image.py
```

The audit compares ram58 against the known-working non-SMP ram57 image. It
checks exact DT node additions, phandle references, unchanged peripheral and
power properties, selected Kconfig changes, the packaged Qt binary, image
size, and the proven WDT2 guard hash. The temporary test uses
`python3 tools/touch10_ram.py session --profile native-thermal` and returns
to stock through the watchdog-protected session controller. The captured
framebuffer is in `evidence/perrier-ram58-thermal-2026-11-09.png`.

On the first live RAM run, `cpu_thermal/temp` was 60795 m°C and TMP102
`temp1_input` was 44625 m°C. Qt logged `cpu_mC=62412 board_mC=44750` at
startup and visibly displayed both values. The measured CPU value is the
thermal framework's hotspot estimate, which can be higher than board air
temperature.

The requested recovery returned to stock Linux `3.4.113+` with its factory
application running. The boot-environment hash before and after the test
matched exactly, and the stock TMP102 still read 45062 m°C.
