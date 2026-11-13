# PCF8574 line mapping: evidence and limits

The Touch 10's stock CE9.9.0 kernel registers an eight-line `pcf8574` on
I2C4 at 0x24 with GPIO base 256. Both copies of its platform data in the
saved kernel image have `n_latch = 0` and no setup callback. The stock driver
initializes a software shadow and reads the port at probe; it does not write
an output value in that path. Mainline's guarded driver does the same.

The saved stock `/sys/kernel/debug/gpio` snapshot lists the chip as GPIOs
256–263 but **no requested line** beneath it. The board initializer
`perrier_init` at `0xc07226b4` and its nearby helpers request SoC GPIOs for
reset, rails, keys and LEDs; no direct `gpio_request` or
`gpio_direction_output` call with a 256–263 constant was found in those
decompiled functions. This does not rule out userspace I2C access or a
consumer in another code path.

The port read is `0x11` on stock and ram96. A PCF8574 has quasi-bidirectional
pins, so this read alone cannot distinguish an externally driven high from
an output latch set high. It neither identifies the eight connected signals
nor establishes a safe value to write. The mainline DT therefore has no
expander GPIO consumers or output hogs. Qt and the diagnostic helper use
GPIO v2 `flags=0` to read all lines without changing their direction.

**Next evidence:** obtain board schematics or trace the eight nets on a
board photograph, then correlate with stock activity. Until then, keep the
expander read-only. Do not infer pin functions from `0x11` or toggle bits to
discover them.

Sources: `out/rtc-expander-audio/stock-expander-analysis.json`,
`../../evidence/perrier-stock-gpio-2026-11-08.txt`, the saved stock kernel
IDA database, and `rtc-gpio-audio.md`.
