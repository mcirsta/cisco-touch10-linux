# Perrier simpledrm RAM trial

This is a separate Linux 6.18.48 candidate from the known-good `simplefb`
ram14 build. It registers mainline `simpledrm` from the inherited
`/chosen/framebuffer@7ec78000` description. The node describes a
1280×800 AR24 buffer with a 5,120-byte stride and spans the three adjacent
Phoenix buffer views. The test never enables OMAP DRM, DSI, a bridge driver,
fbdev, a console, or a touch driver. It does not set a display mode or write
pixels. It inherits the display hardware state established by stock firmware
before kexec.

## Live results

- [ram15 capture](../runs/20261108T140315Z-perrier-simpledrm-trial-83b1ae/serial.log):
  mainline `simpledrm` initialized and created `/dev/dri/card0` and
  `card0-Unknown-1`. The sysfs connector initially showed `unknown` and an
  empty modes file before any DRM master queried it. Stock recovered normally.
- [ram16 capture](../runs/20261108T140828Z-perrier-simpledrm-trial-70cb80/serial.log):
  the first GETRESOURCES query found one CRTC, connector, and encoder. The
  second query returned `EFAULT` because nonzero array counts were paired
  with null pointers in the probe. The device recovered normally.
- [ram17 raw capture](../runs/20261108T141153Z-perrier-simpledrm-trial-215ce1/serial.raw)
  and [offline verification](../runs/20261108T141153Z-perrier-simpledrm-trial-215ce1/verification.json):
  `/dev/dri/card0` opened, GETRESOURCES found one CRTC, connector, and
  encoder, and GETCONNECTOR returned `connection=1` with one
  `1280x800@60` mode. This is simpledrm's synthetic connector state, not
  a hardware link measurement. The helper used GET ioctls only; no SET ioctl or pixel
  write was issued. PID 1 rebooted after 30 seconds. The stock 3.4 kernel,
  `phoenix`, and watchdog returned, and the boot environment SHA-256 was
  unchanged: `f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
  The original runner recorded `failed` because kernel printk split the
  probe's UART lines; [verify_capture.py](verify_capture.py) removes those
  interleaved printk lines and validates the preserved bytes. The runner's
  parser was corrected for future tests. The original result is preserved.
- [ram18 result](../runs/20261108T143720Z-perrier-simpledrm-trial-b7294a/result.json):
  a read-only DISPC snapshot found `CONTROL=0x308`, GFX BA0/BA1
  `0x7f448000`, and GFX attributes `0x0e004099`. The LCD manager enable bit
  in `CONTROL` was clear, while the stock preflight had `0x309` with it set.
  `LINE_STATUS` remained `0x7ff` across a 10 ms interval. During a later
  repeat, the user clarified that the temporary-kernel screen was black,
  then the normal stock UI returned after reboot. This is consistent with
  the LCD manager being disabled. The same run sent one guarded Cypress
  host-mode acknowledgement and sampled touch reports; see
  [touchscreen.md](../perrier/touchscreen.md). simpledrm KMS discovery and all
  recovery checks passed. The ram18 image is preserved in
  [baselines/ram18-touch-ack-dispc](baselines/ram18-touch-ack-dispc).

The reviewed ram17 kernel, DTB, initramfs, helper, config, and manifest are
preserved in [baselines/ram17-kms](baselines/ram17-kms). Its zImage SHA-256
is `2116e4a0c21ea0fcd004e776fd9ca7cd60a5378459092f8f26cc0d3d10e847e4`;
its DTB SHA-256 is `285f5b850f4e4ab4d726880946f287cf987e770894556e394bcc47f11ea39e34`.

## What remains

The KMS result proves device registration and mode discovery. It does not
prove visible scanout, a successful dumb-buffer modeset, or cold-boot display
initialization. During a later ram14 `simplefb` marker trial, the user saw
no green/magenta marker; CPU readback still matched. In a subsequent ram18
trial, the temporary-kernel screen was black and stock UI returned afterward. This
shows that the inherited CPU mapping has not yet been proven to reach the
active scanout. The ram18 register comparison found the LCD manager disabled
after kexec. `simpledrm` describes a framebuffer and offers KMS, but does not
initialize the OMAP display controller or the TC358765 bridge. The next
display work is to reconstruct the stock shutdown and enable sequence from
the saved kernel, then bring up native OMAP DRM and bridge/panel components
only after the clocks, GPIO polarity, and rail sequencing are verified.
Native OMAP DSI and the TC358765 bridge require separate clock, reset, and
power-sequence evidence before enabling them.

The stock touchscreen remains `cyttsp4-i2c` at I2C2 address `0x67`; the RAM
kernel still registers only the I2C controller and reads one status header.
See [touchscreen.md](../perrier/touchscreen.md) for the touch evidence and the
next event-capture step.
