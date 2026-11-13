# Perrier stock MPU supply: static checks

Follow-up: the [exact MLO and stock-kernel rail trace](perrier-mpu-rail-trace-2026-11-12.md)
found matching TWL6032 SMPS1/VCORE1 programming and `mpu` voltage-domain
registration. The narrower uncertainty below reflects the earlier static
pass, before those addresses were decoded.

Examined the saved CE9.9.0 Linux image
`development/stock-kernel/ce990-Image.bin` (SHA-256
`ba6d9c510b6c4fe864d1f29ccd32d5b36b081169e3b130125bc8d412af3b1e18`)
in its existing IDA database, using the saved stock kallsyms for function
addresses. No device memory or persistent state was changed.

- `perrier_init` at `0xc07226b4` calls `idefix4_power_init` at `0xc072251c`.
  The latter calls `omap4_pmic_get_config` and then
  `omap4_pmic_init("twl6032", ...)`. The exact stock boot log confirms
  TWL6032 VCORE1/VCORE2 initialization.
- `CONFIG_OMAP_TPS6236X=y` and the kernel contains
  `omap4_twl_tps62361_enable` at `0xc071d428`, `omap_tps6236x_init` at
  `0xc071d7ac`, and `omap_tps6236x_board_setup` at `0xc071d80c`.
  IDA's analyzed code and data cross-references contain no direct reference
  to those three functions. That is a static observation, not proof that
  no indirect call or earlier bootloader action exists.
- `omap44xx_voltagedomains_init` at `0xc07210a4` selects data according to
  SoC revision and sets voltage-domain pointers. `omap4_opp_init` at
  `0xc071e994` selects OPP data according to SoC revision. Those generic
  functions do not identify the Perrier board's physical MPU regulator.
- Read-only stock sysfs exposes no MPU regulator device; the `userspace`
  governor holds both CPUs at 700 MHz. The I2C client list has no TPS-named
  client. OMAP voltage-controller bypass can address a supply without a
  Linux I2C client, so this absence is inconclusive.

[TI's OMAP4460 U-Boot reference table](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/omap4/hw_data.c?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8)
uses external TPS62361 for MPU and TWL6030/6032 VCORE rails for other
domains. [The OMAP4 SDP board example](https://android.googlesource.com/kernel/omap/%2B/2340c679cabc5477598ee3c9c2044ec8893d42fd%5E2..2340c679cabc5477598ee3c9c2044ec8893d42fd/)
calls `omap_tps6236x_board_setup` explicitly on OMAP4460. Both are reference
designs, not evidence that Cisco wired Perrier identically.

Next: decode the exact Cisco MLO/U-Boot voltage-controller setup and compare
the resulting slave/register addresses with read-only live register state.
Keep CPUfreq and all voltage/VSEL writes disabled until that mapping is
verified. The ram110 dual-core tests retained the bootloader's 700 MHz
setting.
