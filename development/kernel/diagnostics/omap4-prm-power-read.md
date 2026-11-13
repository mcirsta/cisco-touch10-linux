# OMAP4460 PRM power snapshot helper

The [fixed ARM helper](omap4_prm_power_read.c) maps exactly one 4 KiB PRM
page at physical `0x4a307000` through `/dev/mem` with `O_RDONLY` and
`PROT_READ`. It reads 31 fixed, aligned 32-bit registers in the documented
`0x4a307b10`–`0x4a307bac` range. It accepts no arguments and contains no
device register write. The allowlist covers VC command/address/I2C fields,
VP config/limit/step/voltage fields, and the three-domain ramp settings.

The [offline audit](omap4-prm-power-read-review.json) checks the exact
allowlist, page bounds, read-only open/mapping and binary size. A QEMU
user-mode run without `/dev/mem` attempted only an `O_RDONLY` open and
exited. That failure-path test does not prove the actual read on the panel;
the earlier five-word helper successfully used the same read-only mapping
on stock Linux. The new helper is 45,244 bytes, statically linked for ARM.

| Artifact | SHA-256 |
| --- | --- |
| `omap4_prm_power_read.c` | `12145638316c7c6aa8aace43ea4a70347bd81027f31126f0e8f2ee773a0cbe8d` |
| `omap4_prm_power_read.arm` | `4579e0a1c39338f170d8fca2c08042f26584462f179cfc3e67af92f7751aa11d` |

The owner authorized one RAM-only upload and read. The [run record](../../runs/20261113T122951Z-stock-prm-read-800d19/result.json)
shows the hash check, 31-word capture, helper removal, and unchanged stock
boot ID, Linux `3.4.113+`, and Phoenix. The one-use authorization has been
consumed. See the [decoded evidence](../../../evidence/perrier-omap-prm-power-stock-2026-11-13.md).
There was no reboot, device register write or persistent write.

Register addresses and access types come from the local Texas Instruments
OMAP4460 TRM, SWPU235AB, DEVICE_PRM register map. These words describe
programmed requests and limits, not measured supply voltages.
