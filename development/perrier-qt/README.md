# Touch 10 Qt toolchain and calibration UI

This directory builds Qt Quick and the calibration app from source for the
Perrier Touch 10's OMAP4460 Cortex-A9. The target ABI is ARMv7 hard float with
NEON and VFPv3. The old Mija Cortex-A7/VFPv4 runtime is not used by the
staged image.

## Inputs

`downloads/` holds the Qt 6.12.0 base and declarative source archives and a
Bootlin 2026.08 ARMv7 musl cross toolchain (GCC 15.3). Exact SHA-256 checks
are in [prepare_sources.py](prepare_sources.py). The source preparation step
also applies the checked Qt futex time64 compatibility patch in `patches/`.
The source trees and compiler are unpacked under `sources/`, and
[arm-toolchain.cmake](arm-toolchain.cmake) specifies Cortex-A9, NEON, VFPv3,
and the hard-float ABI. The compiler and Qt build products stay in this
directory; the host system Qt is used only for cross-build tools.

Run `bash development/perrier-qt/build_qt.sh` from the workspace root to
configure, build, and install Qtbase and QtDeclarative, build the Touch 10
calibration app and its ALSA dependency, stage the runtime, and run the QEMU preflight. The script
uses Ninja's default parallelism. The installed target libraries are in
`qt-arm/`. To rebuild only the app after editing it, run:

```sh
cmake -S development/perrier-qt/app \
  -B development/perrier-qt/build-arm-a9-local -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/development/perrier-qt/arm-toolchain.cmake" \
  -DCMAKE_PREFIX_PATH="$PWD/development/perrier-qt/qt-arm" \
  -DQT_HOST_PATH=/usr -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build development/perrier-qt/build-arm-a9-local
python3 development/perrier-qt/stage_runtime.py
python3 development/perrier-qt/preflight_qemu.py
```

The staging step copies only the used Qt libraries, QML modules, linuxfb and
offscreen plugins, target C++ runtime, loader, font, and the newly compiled
`perrier-touch-grid`. It strips binaries and records SHA-256 hashes in
`runtime-manifest.json`. The QEMU preflight runs the staged app under a
Cortex-A9 CPU model with a shortened timer and checks both its ready marker
and a clean exit.

The RAM kernel needs fbdev emulation, evdev, futex, shared memory,
eventfd, Unix domain sockets, and signalfd. The [interactive RAM
environment](../perrier-ramenv/README.md) starts Qt over SSH and keeps the
watchdog recovery active. No Qt files are installed on the eMMC.

The linuxfb plugin's evdev input thread caused a repeatable exit crash on
this kernel. The Qt launcher disables that thread; the diagnostic app reads
the bridge or native input device on its main event loop. Timed and
SIGTERM exits now return normally. The grid uses direct touch X/Y and normal
Qt layout. In the first RAM kernel, the panel rotated framebuffer scanout by
about +214 pixels. The kernel now selects the stock DISPC core clock during
display enable; the user confirmed correct targets and touch tracking with
zero Qt shift in the
[live calibration](../../evidence/perrier-qt-horizontal-calibration-2026-11-09.md).
The temporary scene compensation and movable-center controls are removed
from the app and runner; their sources are preserved in
[the diagnostic archive](archive/ram44-display-shift-diagnostic/manifest.json).
The Qt reader now accepts either the old RAM bridge or the native Gen4 kernel
input node. It searches `/dev/input/event0` through `event7`, checks the
device name and 1280×800 axes, and tracks multitouch slots on its main event
loop. The cleaned app was restarted on the same confirmed RAM kernel without a
reboot. Optional input mirror/offset controls remain for diagnostics, with
neither enabled by default. The native Gen4 input driver now reports directly
to this evdev reader.

The `ram51` diagnostic UI adds a four-stop backlight slider at the bottom of
the screen. The app enables it only when the kernel reports a backlight with
`max_brightness=4`, and its touch reader writes levels 1 through 4 to
`/sys/class/backlight/backlight/brightness`. Level zero is excluded so a
drag cannot make the panel unreadable. The app restores the brightness it
found on normal exit. A user drag exercised all four levels through the
mainline timer10 PWM driver; the user confirmed that the backlight changed
and the red touch marker followed the finger. The cyan comparison marker
was removed afterward. The current RAM framebuffer
[screenshot](../../evidence/perrier-ram51-slider-clean-fb-2026-11-09.png)
shows the slider and aligned targets. GPIO157 power sequencing and pad mux
setup still need a cold-boot port.

The `ram52` test screen also has a simulated volume slider and mute box.
`RamKeyReader` opens the native `4a31c000.keypad` evdev node by name. A new
volume press moves five points; held-key repeat events move two points at
most once every 80 ms so the motion stays visible. A mute press toggles the
state once, while repeat and release events do not toggle it. The UI shows
the repeat and mute-press counts. Touch can drag the simulated volume slider
or toggle the mute box; neither control changes audio hardware. The
[initial framebuffer screenshot](../../evidence/perrier-ram52-volume-mute-2026-11-09.png)
was captured during the RAM test.
The user held the front volume keys and mute button and confirmed the UI
responded. The [test record](../../evidence/perrier-ram52-volume-mute-test-2026-11-09.md)
includes event counts, the log, and a post-test screenshot.

The speaker-audio build replaces that simulation with native ALSA mixer
control. Build ALSA first with
`python3 development/audio/build_application_audio.py`, then run the app
build/staging commands above. `audio_backend.cpp` checks the Perrier card,
gain ranges and output state before enabling controls. Each change is
verified by mixer readback; normal exit restores the original gain/route.
Volume maps to HFR gain 0–24, with zero and mute disabling HFR. The other
outputs remain off. The usual keys, held-key repeat and touch slider all
drive this same backend.

The Test sound button starts/stops a bounded 30-second 48 kHz mono S16_LE
beep sequence. ALSA's standard plugins resample/map it into the native
96 kHz four-channel PCM, only HFR active. Explicit period/buffer frame
sizes are in `pcm_setup.h`; the high-level period-time helper was ambiguous
through this plugin chain. Audio writes run on a nonblocking worker so Qt
and the watchdog remain responsive. `/run/qt-audio.json` reports mixer
state, playback frames and errors for SSH diagnostics. This file is in RAM.
See [the audio build and mapping notes](../audio/README.md).

Ram94 connects the mute demo to the native `red:micmute` and
`green:micmute` LED class devices. The app checks that both are binary
LEDs, lights red when muted and green otherwise, and restores their prior
state on exit. It uses LED sysfs rather than GPIO export or MMIO. The owner
confirmed both physical colors; 20 front mute presses produced matching
readback. The volume slider remains a simulation; audio hardware support
is a later kernel stage. The kernel's two LED pads and active-high polarity
come from the stock board data and live readback, with no custom LED driver.

Ram95 adds six live INA3221 voltage/current rows and a White LED button.
The rows identify each physical monitor address and channel, without guessing
rail names. Values come from the mainline hwmon input/current files every
two seconds. The button switches `white:status` between off and the stock
startup level 10/255, with readback and prior-state restoration on exit.
The owner confirmed physical on/off control; ten verified Qt changes were
captured. These checks kept the display and Qt running throughout.

Ram96 adds two read-only status cards: RTC calendar/counter and the GPIO
expander's port byte in hexadecimal and binary. The RTC uses RTC_RD_TIME;
its calendar is deliberately left at the stock unconfigured date. The GPIO
reader identifies the eight-line `pcf8574` chip and uses GPIO v2 flags=0
(AS IS), without selecting direction, bias, drive or values. It releases
the lines after each read and skips a busy sample. The new kernel APIs and
one restored RTC alarm passed in one RAM boot with the same Qt PID
throughout, no display cycles and no Qt restarts. A
[progress screenshot](../runs/20261112T094548Z-uboot-ram96-0df43b/aux-framebuffer.png)
is saved on the PC.

The ram58 build adds a Temperatures card with live CPU and Board readings.
The values come from the mainline OMAP4460 `cpu_thermal` zone and TMP102
hwmon driver, refreshed every two seconds. The
[RAM framebuffer screenshot](../../evidence/perrier-ram58-thermal-2026-11-09.png)
shows both readings alongside the existing touch, volume, mute, and
backlight controls. The sensor and safety notes are in
[`perrier-thermal/README.md`](../perrier-thermal/README.md).
