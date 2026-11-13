# Workspace instructions

- When building with Ninja, use its default parallelism. Do not pass a fixed
  job count or set `CMAKE_BUILD_PARALLEL_LEVEL` unless the user requests it.
- Use `ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10` for
  Touch 10 device access. This key-based root SSH connection was verified
  after a device reboot.
- The current recovery work is investigation only. Use read-only device
  commands and offline analysis of the saved backup. Do not change U-Boot
  environment, GPT, boot partitions, firmware, recovery selector, or other
  device state unless the user explicitly changes this scope.
- Standing owner authorization (2026-11-12): restore the three ADC sensing
  controls after ADC RAM tests to saved stock values: I2C 0x48:e4 to 0x00,
  0x49:04 to 0x04, and 0x49:06 to 0x14. Use the reviewed, hash-pinned
  `restore_adc_measurements.c` helper through the U-Boot runner's ADC
  postflight. Authorization and its exact helper hash are recorded in
  `development/kernel/out/native-diagnostics/adc-postflight-authorization.json`.
  This same bounded cleanup is authorized for future ADC RAM tests; other
  recovery changes remain investigation only unless separately authorized.
