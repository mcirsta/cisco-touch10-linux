# Perrier 48 kHz application audio and Qt controls

This phase adds userspace support on the qualified ram97 hardware setup.
Kernel sources, hardware configuration, board DTB, display setup and the
watchdog helper are unchanged. The new packages contain ALSA's upstream
library/configuration, `aplay` and the recompiled Qt application.

## Playback and controls

The default ALSA PCM accepts mono/stereo application playback at 48 kHz
S16_LE. Standard plug/rate/route plugins convert to 96 kHz S32_LE and put
the averaged signal in HFR slot 3 of the four-channel McPDM stream.
Mono is duplicated before averaging. Slots 0–2 remain silent. No codec
rate advertisement or hardware clock was changed to claim native 48 kHz.

Qt owns `Handsfree Playback Volume` and `Handsfree Right Playback` through
ALSA's native control API. It validates the Perrier card, control types,
gain limits and route names, and requires the other outputs to be off.
The UI maps 0–100% to right gain 0–24, capped at the stock observed setting.
Zero or mute selects Off; unmute selects HF DAC with the current gain.
Every mixer write is read back. Normal exit restores the original gain
and route, which was verified during the RAM-only app correction.

Touch and held front volume keys use the same backend. Mute toggles once
per press and drives the existing red/green indicators. The Test sound
button runs a bounded 30-second, faded 660 Hz sequence at about -24 dBFS
on a nonblocking worker; ALSA writes do not occupy Qt's event loop.
`/run/qt-audio.json` gives SSH access to playback and mixer state.

The default PCM permits one playback client at a time. Concurrent mixing,
stock ABE DSP processing and production power management are separate work.
No additional physical speaker or earpiece is inferred; EP stays off.

## Offline verification

The real ARM `aplay` and ALSA library ran under a QEMU Cortex-A9 model,
replacing only the hardware sink with the file/null plugin. Six tests
verified mono unity gain, stereo averaging, left/right half level,
opposite-phase cancellation, full-scale headroom and zero samples in
slots 0–2. Actual production configuration bytes were used. Reports are in
`out/application-audio/conversion-checks.json` and both source snapshots.
The Qt application also passed QEMU start/clean exit checks.

## Initial ram98 failure and correction

Run `../runs/20261112T111512Z-uboot-ram98-dc6330/` booted through U-Boot.
Mono and stereo 48 kHz `aplay` passed, but Qt's first test-button attempt
returned Invalid argument. ALSA's `snd_pcm_set_params()` helper selected a
period time whose frame-size interval was unresolved through this rate
plugin chain. The error occurred before committing PCM hardware parameters.

The correction uses explicit period/buffer sizes, as the working `aplay`
path does: 1,024 and 4,096 application frames respectively. The exact
function is shared in `pcm_setup.h` with a silent diagnostic. Both QEMU
and panel execution passed. The helper's first frame-count assertion
expected exactly 144,000 frames but its loop submitted a final partial
chunk beyond that target; setup/playback itself passed. The diagnostic
was corrected to bound that final write, and the final panel run returned
exactly 144,000 frames. These original logs are preserved.

The corrected Qt binary was uploaded over RAM SSH and cleanly restarted
once. No kernel reboot or display reset was used for the software fix.
The owner confirmed “Tones, volume and mute work.” Native front volume
up/down hold and mute events are in the Qt log. All 124 stable independent
mixer samples matched Qt. Twenty-six active PCM samples included muted
and unmuted states: DMA continued while HFR was Off during mute. Volume
zero also disabled HFR. The 30-second Qt stream completed 1,440,000
application frames with zero recoveries. All 65 sampled PMIC fields
remained unchanged. Ram98 is preserved as not promoted because its packed
Qt binary predates this correction.

## Repeatable ram99 image

Profile `speaker-audio` contains the exact corrected Qt binary, SHA-256
`384466222476f0b631ecc318117cf0716caacde07ebdbb4d9d51346b71929eb8`.
The immutable snapshot is `baselines/ram99` (138 files, eleven unchanged
kernel patches). Run `../runs/20261112T112823Z-uboot-ram99-c29ec2/` verifies
the packaged binary's hash against the owner-confirmed RAM update.
It repeats mono/stereo application playback, the exact Qt PCM setup with
144,000 silent frames, mixer startup, storage safeguards and rail checks.
Qt starts once in this final image; there are no Qt restarts or display
reset cycles. The owner observation is reused by binary identity rather
than described as another physical test.

Both sessions use the established one-shot U-Boot factory-restore path,
read-only/unmounted eMMC in RAM Linux, root SSH and unchanged nowayout
watchdog/host lease. Final promotion requires hardware expiry, healthy
stock Phoenix, exact factory p8 and matching stock audio/rail checks.
See `validation-ram99.json` for the final outcome and recovery timing.
Ram97 remains the immediate fallback.
