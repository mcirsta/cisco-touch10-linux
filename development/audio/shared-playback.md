# Concurrent speaker playback candidate

The qualified ram100 image still uses one client per PCM. A candidate built
from the pinned upstream alsa-lib commit `f44e0abd5382f519cc6fa69850c34e6e9c09d5f5`
adds only its `dmix` plugin. The candidate configuration places `dmix` at
the native 96 kHz, four-channel, S32_LE McPDM PCM. The existing 48 kHz
application conversion and HFR slot-3 routing are retained. No kernel,
display, touch, PMIC rail or Qt binary was changed for this trial.

Files: [configuration](asound-mix.conf), [isolated builder](build_dmix_lib.py),
[two-client hardware check](test_concurrent_playback.py). The stripped ARM
candidate is `shared-install/libasound-dmix.so.2`, SHA-256
`e01c0a218e51b28af78f160758171582df1c560c5d6b0deb885a`. The
configuration SHA-256 is
`c0f0b990860bd7bd5b42dbef97b2a608e98a3d3e7cf42bbdd94891cbd6a6ed65`.
The original qualified ALSA library and image remain unchanged.

## Live ram100 test, 2026-11-12

One already qualified U-Boot RAM boot tested two independent 8-second silent
48 kHz application streams, started one second apart. With the original
config/library, the first stream exited 0 and the second exited 1 with
`Resource busy` (8.23 seconds elapsed). With the candidate library and
configuration in RAM-only `/tmp`, both exited 0 (9.31 seconds elapsed).
This establishes shared open and concurrent drain through the real speaker
PCM. A verbose single-stream run showed the 96 kHz, four-channel S32_LE
hardware sink. The mixed waveform itself has not been captured electrically.

The first candidate attempt failed because `dmix` was absent from the ALSA
build. The next attempt reached `dmix` but lacked ALSA's global timer
definition because `ALSA_CONFIG_PATH` replaced the global file. The passing
test prepended the installed global config without its top-level
`/etc/asound.conf` loader hook, then appended the candidate config. A
packaged image should install the candidate as `/etc/asound.conf` and let
the ordinary global loader hook load it. That packaging path still needs a
single bundled RAM validation alongside other support changes.

The same RAM session also tested volatile system-clock synchronization from
the host. The initial kernel clock was 174 seconds after 1970; setting it to
the host epoch succeeded. The TWL RTC remained in year 2000, Qt PID 114 did
not change, and the watchdog kept feeding. The recorded second check is
[`ram-clock-sync.json`](../kernel/out/ram-clock-sync.json); its reusable
helper is [`sync_ram_clock.py`](../kernel/sync_ram_clock.py). A persistent
production clock source remains separate from this RAM-session aid.

The controller returned to healthy stock Linux 3.4.113+ with factory p8
SHA-256 `f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
The approved ADC postflight passed and restored `48:e4=00`, `49:04=04`,
`49:06=14`. Run record:
`development/runs/20261112T134011Z-uboot-ram100-1cc710/result.json`.
No display blank/unblank cycle or Qt restart was requested.
