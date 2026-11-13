# Ram104 packaged shared playback

The qualified `mailbox-audio-dt` image installs the pinned upstream ALSA
`dmix` build and [`asound-mix.conf`](asound-mix.conf) through the normal
`/etc/asound.conf` loader. It mixes at the native 96 kHz, four-channel,
S32_LE McPDM sink. The 48 kHz application conversion and HFR slot-3 route
are inherited from ram99.

Two overlapping silent 48 kHz clients both exited successfully in 9.3
seconds. The same package passed on the intermediate ram103 image. No
electrical waveform capture or acoustic mixing test was done. The run
evidence is [`packaged-dmix.json`](../runs/20261112T141303Z-uboot-ram104-9d19fd/packaged-dmix.json),
and the full boot and recovery record is
[`validation-ram104.json`](../kernel/validation-ram104.json).

The image also bound the upstream OMAP mailbox and hardware-spinlock
providers. Qt stayed on its original PID, the nowayout watchdog fed, and
the panel returned to healthy stock. Factory p8 and the approved ADC
postflight passed. No display blank/unblank or Qt restart was performed.
