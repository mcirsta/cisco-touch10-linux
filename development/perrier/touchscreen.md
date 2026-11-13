# Touch 10 touchscreen status, 2026-11-08

Update, 2026-11-09: a [native Gen4 kernel input driver](../perrier-touch/README.md)
is built and running in the separate `native-touch` RAM image. The earlier
sections below preserve the steps that established the controller protocol
and the initial display scanout investigation. The live driver registered a
1280×800, ten-contact input device at `/dev/input/event0`, but the `ram45`
panel image wrapped horizontally. The later `ram50` image now programs the
bridge before pixel scanout and matches the stock bridge registers. The user
confirmed the five targets were physically aligned, and the native input
driver reported direct coordinates near each target. All ten tracking slots
were idle after the taps. See the [native touch log](../../evidence/perrier-ram50-native-touch-qt-2026-11-09.log).

## Interactive RAM trial, 2026-11-09

The [interactive RAM image](../perrier-ramenv/README.md) keeps Linux 6.18.48,
Qt 6.12, and the Gen4 I2C-to-uinput bridge running under SSH and an inherited
hardware watchdog. The first recovery proof returned stock after the feeder
stopped; subsequent Qt rebuilds now upload and restart on the **same** RAM
kernel boot ID.

Qt's linuxfb evdev worker caused a repeatable SIGSEGV in `QObject::~QObject`
on shutdown. Disabling that worker and reading `/dev/input/event0` through a
`QSocketNotifier` in the app's main event loop removed the crash: timed exit,
SIGTERM exit, and repeated launch all returned zero. A host GDB stack and
serial records are in `../perrier-ramenv/qt-exit-gdb.log` and the interactive
run folder.

The stock coordinated taps below show direct X/Y touch coordinates. The
apparent contradiction between earlier red/cyan reports was caused by the
**display scanout**: the physical image was a cyclic horizontal rotation of
the 1280-pixel framebuffer by approximately +214 pixels. Before correction,
the framebuffer's X=430 target appeared at the panel's physical center;
X=90 appeared near physical X=304, while X=1190 wrapped to physical X=124.
The [before photo](../../evidence/perrier-qt-before-wrap-2026-11-09.jpg)
shows both corner pairs on the left half. `/dev/fb0` and the DISPC GFX base
address agree on an unpanned 1280×800 framebuffer, so the rotation is later
in the display path. The stock and RAM DSI comparisons also differ in the
FIFO emptiness counter and VC2/3 control registers; the active VC0/1 register
values match. Changing the DSS core clock mux after display enable did not
remove the offset, and that live register change was restored.

Qt temporarily rendered a cyclic X=-214 translation of the entire scene
with **direct** touch X/Y. The [after photo](../../evidence/perrier-qt-aligned-2026-11-09.jpg)
shows all five targets in their expected panel positions. The same live RAM
boot logged taps at center `(635,399)`, upper-left `(78,121)`, upper-right
`(1155,137)`, lower-left `(98,709)`, and lower-right `(1172,704)`, close to
their printed targets `(640,400)`, `(90,130)`, `(1190,130)`, `(90,710)`, and
`(1190,710)`. The user confirmed that the red marker tracks their finger.
The [calibration evidence](../../evidence/perrier-qt-horizontal-calibration-2026-11-09.md)
records the mapping. The RAM DISPC core clock was 170.667 MHz instead of
stock's 142.147 MHz. A board-gated kernel patch now selects the stock source
at display enable. Its readback matches stock, and the user confirmed
"Everything aligns" with zero Qt shift, center X=640, and direct input in
the [2026-11-09 confirmation](../../evidence/perrier-clockfix-confirmed-2026-11-09.txt).
The active Qt app and runner no longer contain the scene-shift or movable
center workaround. The cleaned app was rebuilt and restarted on the same
kernel boot `3bd1c2f8-cfda-443c-9162-2986e4618e50`. The display-clock fix
resolves the apparent mirroring; the exact internal timing mechanism remains
an inference. Automatic stock recovery with this kernel patch had already
passed in the preceding interactive run, with an unchanged boot environment.

The installed CE9.9.0 kernel binds `cyttsp4-i2c` at I2C2 address `0x67` as
`/dev/input/event1`. Its driver state after the ram17 simpledrm trial was
`ACTIVE`; firmware identity was product `0x0001`, version `1.1`, revision
`0000000000066c47`. The factory `phoenix` application was running. The stock
input capabilities include `ABS_MT_TOUCH_MAJOR`, `ABS_MT_POSITION_X`,
`ABS_MT_POSITION_Y`, `ABS_MT_TRACKING_ID`, and `ABS_MT_PRESSURE`. The stock
`drv_param` table reports 1280 and 800 in entries 4 and 5. Source data is in
[touch params](../../evidence/perrier-touch-params-2026-11-08.txt),
[touch sysfs](../../evidence/perrier-touch-sysfs-2026-11-08.txt), and
[hardware safety](hardware-safety.md).

The ram11 kernel read the 16-byte controller header
`80006603000000000302000000000000` with a register-zero I2C read. The ram14
kernel read 64 bytes every 100 ms for 30 seconds; all 300 reads succeeded and
the bytes stayed identical with no coordinated touch. These checks establish
I2C communication and an idle baseline. They do not establish event decoding
or a working mainline input device. A center tap, corner taps, and a short
drag during a bounded stock `/dev/input/event1` capture should provide
known-good coordinates and release/slot behavior. A parallel, bounded raw
I2C capture in the RAM kernel can then map report bytes to those input events.
The host-side [capture_stock_touch.py](../../tools/capture_stock_touch.py)
is ready for the stock event pass. It runs `cat /dev/input/event1` over SSH
for a bounded interval and decodes ARM32 `input_event` records locally; it
does not write to the panel.
A three-second passive [test capture](../../evidence/perrier-touch-passive-2026-11-08/events.json)
completed with no events while the panel was idle. Its host timeout left the
remote `cat` blocked; the identified reader was stopped, and the capture
tool now uses a remote timer and exit trap. A two-second
[cleanup retest](../../evidence/perrier-touch-passive-cleanup-2026-11-08/events.json)
captured zero idle events, returned normally, and left no `cat` process.
The factory touch driver remained `ACTIVE`. Neither test establishes touch
coordinates.

## Coordinated stock event capture

The [60-second event capture](../../evidence/perrier-touch-taps-2026-11-08/events.json)
recorded 1,239 complete ARM32 `input_event` records (19,824 bytes; SHA-256
`cc7d65d0104519ca01dd5833f747c6da13aad7a79c512f720d0fbe47b8012275`).
They form seven contacts: center `(634,436)`, upper-left `(21,2)`,
upper-right `(1228,66)`, lower-right `(1243,761)`, lower-left `(49,765)`,
then two drags from `(202,153)` to `(1016,547)` and from `(270,761)` to
`(1006,182)`. This confirms a direct 1280×800 orientation in stock input,
without an axis swap or mirror. Samples carry X, Y, pressure, major-axis
size, and tracking ID. The driver uses type-A multitouch frames: each
contact report ends with `SYN_MT_REPORT` followed by `SYN_REPORT`, while a
release has only an empty `SYN_MT_REPORT`/`SYN_REPORT` frame. The observed
single-finger tracking ID was `1` throughout; multi-finger behavior is not
yet characterized. The remote reader exited normally and the factory
touch driver remained `ACTIVE`.

## Temporary-kernel raw comparison

The known-good ram14 [trial](../runs/20261108T142753Z-perrier-trial-8e8de7/result.json)
sampled the first 64 I2C bytes 300 times at 100 ms intervals. All reads
succeeded, but the header stayed identical and `changes=0`. The first 16
bytes were `80006603000000000302800000000000`, with byte 10 at `0x80`
instead of the earlier idle `0x00`. The trial passed its other checks,
rebooted to stock, restored `phoenix`, and kept the boot environment hash
unchanged. The user confirmed tapping during this exact RAM capture. The
archived Gen4 source reads status
on an IRQ and then toggles host-mode bit 7 to acknowledge the report. The
RAM sampler only reads register zero and never performs that handshake, so a
stale report is a plausible explanation, not a verified diagnosis. IDA
disassembly of the saved Cisco kernel's `_cyttsp4_handshake` at `0xc02ee688`
confirms a one-byte host-mode write to register zero that toggles bit 7;
`_cyttsp4_xy_worker` reads status and touch data before that acknowledgement.
The exact image SHA-256 is
`ba6d9c510b6c4fe864d1f29ccd32d5b36b081169e3b130125bc8d412af3b1e18`.
A bounded follow-up can acknowledge one existing report, then sample for a
new touch without touching GPIOs, rails, firmware, or storage.

The audited ram18 [trial](../runs/20261108T143720Z-perrier-simpledrm-trial-b7294a/result.json)
did that once. It read host mode `0x80`, wrote `0x00` as a two-byte I2C
transaction consisting of register address and one data byte, and observed
host mode `0x00` in its first following sample. All 300 subsequent 64-byte
reads succeeded, but `changes=0`; no new report appeared. Whether the user
finished tapping during this exact second window is awaiting confirmation.
The later 16-byte header read, roughly ten seconds after the sampling window,
returned host mode `0x80` again. The capture cannot tell when or why that
transition occurred.
The stock kernel, `phoenix`, and `ACTIVE` touch driver returned; the boot
environment SHA-256 did not change. The one-ack path and its reviewed image
are preserved in [ram18-touch-ack-dispc](../perrier-simpledrm/baselines/ram18-touch-ack-dispc).
The next investigation is to compare GPIO 120/121 touch-power states, GPIO
141 reset and GPIO 142 IRQ states, and the controller's operational status
before/after kexec. This can begin with passive register reads. Do not infer
that repeating the acknowledgement or adding a driver will restore scanning.

The stock board code identifies GPIO 141 as `cyttsp4_reset`, GPIO 142 as
`cyttsp4_irq`, and GPIOs 120/121 as touch power controls. The RAM DT omits
these controls, and `CONFIG_INPUT=n`; no mainline touchscreen driver has been
bound. The archived [Cypress Gen4 GPL source](../reference/cyttsp4-android-common-4a2c9b037a08/README.md)
is a protocol reference, not an exact copy of the Cisco driver. Its probe
calls board reset/initialization and can load firmware. A board driver must
keep firmware updating and rail/reset actions disabled until the board
sequence and protocol are verified. A passive event capture on stock needs
no power cycle.

## Visible native-kernel touch evidence, 2026-11-09

The [ram37 run](../runs/20261109T091541Z-perrier-simpledrm-trial-4fcddd/result.json)
compared the stock and temporary-kernel GPIO levels while the native DRM
pattern ran. GPIO120 and GPIO121 touch supplies remained outputs high;
GPIO141 reset remained output high; GPIO142 IRQ remained input high at idle.
The pattern, automatic stock recovery, and boot-environment hash check passed.
The older idle raw captures therefore cannot be explained by an obvious
change in these four GPIO levels.

The [ram38 run](../runs/20261109T092412Z-perrier-simpledrm-trial-237d0c/result.json)
sampled the Gen4 controller's first 64 I2C bytes and GPIO142 every 50 ms for
30 seconds while the user tapped and dragged. It recorded 19 changed reports,
16 IRQ edges, and no I2C errors. Reports included one contact at bytes 12–18,
with big-endian X at bytes 12–13 and Y at bytes 14–15. Examples were
`(602,403)`, `(16,25)`, and `(1252,761)`. The report length at byte 9 was
`2 + 7 * contacts`, with the contact count in byte 11. Two-contact records
also appeared. This layout is inferred from the observed frames and is not
yet a complete Gen4 driver specification. The captured RAM image is saved in
[ram38-touch-irq-capture](../perrier-native/baselines/ram38-touch-irq-capture).

The [ram39 run](../runs/20261109T093017Z-perrier-simpledrm-trial-16fb58/result.json)
drew 44 visual contact markers directly into the DRM dumb buffer. The user
saw the red squares, confirming live pixel updates after modeset, but reported
that their positions did not match the touches; a left/right mirror is likely
but has not been isolated. This run also recorded 39 IRQ edges and no I2C
errors. Stock Linux 3.4, Phoenix, and the U-Boot environment returned normally.

The next calibration step is a small Qt Quick grid in the RAM image. It shows
both raw and left/right-mirrored positions at the same time. The RAM image
now has DRM fbdev emulation and a temporary userspace I2C-to-uinput bridge;
the bridge emits one type-B contact for Qt and does not reset the controller,
change power rails, or request firmware loading. This bridge is a development
tool; the long-term kernel path is a bounded Gen4 input driver using the
controller's sysinfo layout and IRQ/handshake protocol. Mainline `cyttsp`
supports the older Txx3xx family and `cyttsp5` targets Gen5, so neither is
bound to this controller without protocol work.

The first Qt trial used Mija's prebuilt Cortex-A7/VFPv4 Qt runtime. The
[ram40 run](../runs/20261109T095134Z-perrier-simpledrm-trial-720dc7/result.json)
brought up `/dev/fb0` and `/dev/input/event0` but the Qt process terminated
with signal 4 before drawing. The Touch 10's `/proc/cpuinfo` reports a
Cortex-A9 with NEON and VFPv3. Stock recovery and the environment hash check
passed. Qt 6.12 and the Touch 10 calibration app have since been compiled
from source with a local GCC 15.3 cross toolchain targeting Cortex-A9, NEON,
VFPv3, and hard float. The second
[ram40 run](../runs/20261109T100850Z-perrier-simpledrm-trial-a3856c/result.json)
got past the CPU instruction failure but Qt's event loop exited because
`eventfd()` returned `ENOSYS`: the minimal kernel omitted `CONFIG_EVENTFD`.
The panel again recovered to stock with an unchanged U-Boot environment.
The [toolchain and Qt build](../perrier-qt/README.md) now live in this
workspace. The next RAM image enables eventfd before repeating the grid test.

The [ram41 run](../runs/20261109T102723Z-perrier-simpledrm-trial-2f3026/result.json)
enabled eventfd and ran the newly compiled Qt Quick grid for its full
50-second window. The temporary I2C-to-uinput bridge logged 20 contact
positions at the center, corners, and along drags. The user observed that
the red, direct-coordinate dot appeared under their finger, while the cyan
dot was the deliberate left/right mirror. This suggested a direct mapping,
but the subsequent ram42 observation disagreed; orientation remains open.
The Qt event loop reported exit status zero, but the process then ended with
signal 11 during cleanup, so the run's strict completion gate failed. Qt's
linuxfb virtual-terminal helper also reported that `socketpair(AF_UNIX)`
was unavailable; `CONFIG_UNIX` was absent from the minimal kernel. The panel
returned to stock, Phoenix ran, and the boot-environment hash was unchanged.
The next RAM image enables Unix domain sockets and retains only the red dot.

The [ram42 run](../runs/20261109T103256Z-perrier-simpledrm-trial-0d9fe3/result.json)
enabled `CONFIG_UNIX`; Qt no longer reported a `socketpair()` error. It
displayed the single red marker and logged 18 raw touch positions. The user
reported that this marker appeared horizontally mirrored, which conflicts
with their first grid observation. The grid orientation itself was not
confirmed. Qt again completed its event loop, then aborted during linuxfb
teardown with `pure virtual method called`. Stock boot and the environment
hash check passed. A follow-up diagnostic grid restores both markers, labels
the corners, and logs Qt's press coordinates so the raw I2C value, Qt event,
and visible position can be compared independently. That RAM-only app exits
with `_Exit` after the timer to avoid the known teardown abort; this is a
test-process workaround, not a fix for Qt's linuxfb cleanup.
The ram43 image and app have passed offline build, patchset, board audit,
and Cortex-A9 QEMU preflight. The four-corner live calibration is deferred
until the user can watch the panel.

## Native Gen4 kernel input driver, 2026-11-09

The full system-information descriptor was captured from the running
controller. It reports firmware 1.1, a 1280×800 sensor, up to ten contacts,
seven-byte contact records, and an 82-byte maximum operational frame. The
[capture](../../evidence/perrier-touch-sysinfo-2026-11-09.txt) restored the
controller to operational mode. Twenty saved reports and synthetic edge cases
pass the [parser replay](../perrier-touch/test_protocol.py), including a
release and a new press in one frame.

The `native-touch` RAM profile uses a kernel I2C touchscreen driver, a
threaded GPIO142 interrupt, and Linux type-B multitouch slots. It does not
include the I2C-to-uinput bridge. The new DT node claims only the IRQ; reset,
power, pinmux, and voltage states are inherited from stock during kexec.
The [image audit](../perrier-ramenv/native-touch/reviewed-image.json) passed.
In the [live RAM session](../runs/20261109T162416Z-interactive-17a1c1/result.json),
Linux registered `Cypress CYTTSP4` as `/dev/input/event0` with direct X/Y
ranges of 0–1279 and 0–799. Qt opened that device, SSH was available, and the
watchdog lease fed throughout the test. The user's panel photos showed a
horizontal display wrap despite a correct framebuffer capture; a display
off/on cycle changed its phase and did not fix it. The run returned to stock
with the boot environment unchanged. The next RAM candidate moves Toshiba
bridge programming ahead of DSI video start, matching the stock order.
Physical touch alignment is still pending. The driver sources, patch set, build
commands, and recovery behavior are documented in the
[native touch README](../perrier-touch/README.md).
