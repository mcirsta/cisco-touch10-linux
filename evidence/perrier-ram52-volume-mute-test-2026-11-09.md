# Touch 10 front-button Qt test

The existing audited Linux `6.18.48-perrier-ram52` image booted through kexec
with the watchdog recovery lease. The Qt app was rebuilt from source, staged,
passed the Cortex-A9 QEMU startup/exit preflight, and hot-restarted over RAM
SSH without rebuilding the kernel.

The app opened `/dev/input/event0` as `4a31c000.keypad` and the native
Cypress touch input as event1. The user held both volume buttons and tested
mute on the physical panel, then reported that everything worked.

The [live Qt log](perrier-ram52-volume-mute-live-2026-11-09.txt) contains:

| Key | Presses | Repeat events | Releases | UI effect |
| --- | ---: | ---: | ---: | --- |
| Volume down (114) | 1 | 54 | 1 | Slider moved down |
| Volume up (115) | 1 | 103 | 1 | Slider moved up |
| Mute (113) | 3 | 52 | 3 | Exactly three toggles, one per press |

The simulated volume traversed 0 through 100. Mute repeat events did not
toggle the state. No Qt input or backlight read errors appeared. A touch drag
also changed the separate backlight slider from level 4 to 3 and back to 4.
The [initial screenshot](perrier-ram52-volume-mute-2026-11-09.png) shows
volume 50% and sound on; the [post-test screenshot](perrier-ram52-volume-mute-after-2026-11-09.png)
shows volume 100% and muted. These volume and mute values are simulated in
Qt and do not change the ALSA mixer or audio hardware.

The [RAM session result](../development/runs/20261109T191250Z-interactive-42db87/result.json)
is `passed`: stock Linux returned and the U-Boot environment hash stayed
unchanged.
