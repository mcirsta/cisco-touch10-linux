# Perrier native audio tools

The RAM audio test uses the existing mainline TWL6040 MFD, codec and clock
drivers, OMAP McPDM and SDMA. The card driver has one generic correction:
use the required DT audio-routing table without also adding the generic
all-endpoint table. The board wiring comes from Perrier's stock kernel,
not the other Touch 10 board variant.

`tinyalsa/` is upstream [TinyALSA](https://github.com/tinyalsa/tinyalsa),
commit `a7cd26a17fe2add2ff38d2f281ed0b919187a068`. It is compiled from source
with the existing Bootlin GCC 15.3 ARMv7 musl toolchain, Cortex-A9, NEON and
hard-float ABI. The tools are static and plugin support is disabled.

```sh
cmake -S development/audio/tinyalsa -B development/audio/build -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/development/audio/arm-toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=MinSizeRel -DBUILD_SHARED_LIBS=OFF \
  -DTINYALSA_USES_PLUGINS=OFF -DTINYALSA_BUILD_EXAMPLES=OFF
cmake --build development/audio/build
```

The CMake policy argument allows this upstream project's older minimum
version with the installed CMake. Its sources are unmodified. Ninja uses
default parallelism. QEMU Cortex-A9 startup checks passed for the tools.
`manifest.json` records source/tool hashes and the first test files;
`manifest96k.json` records the corrected native-rate inputs actually used.
Executed copies and hashes are saved with the live run.

Perrier's stock `alsafifo` accepts mono 48 kHz S16_LE audio through the ABE
path. Mainline's direct McPDM DAI advertises 88.2/96 kHz S32_LE. Both native
rate families passed silent DMA/timestamp checks. HFR is legacy PCM slot 3,
so the direct test uses four channels with the signal only in slot 3.
The initial 48 kHz direct-device test was rejected; that evidence is kept.
Use a standard userspace resampler/channel mapper for normal 48 kHz mono
or stereo application audio rather than changing the hardware DAI's rates.

Three HFR tones at -24 dB hardware gain and about -24 dBFS PCM were heard
by the owner. Routes and gains were restored afterward. EP is a generic
codec output name: its board flag does not prove a separate physical
earpiece. EP PCM/DAPM and DAC/amp activation passed, but neither minimum
nor modest-gain tests produced audible sound. Keep that path unqualified;
the active stock route is HFR. No external accessory is needed for the
confirmed internal-speaker path.

The ram99/100 application-audio path uses ALSA's upstream plugins in
[`asound.conf`](asound.conf): mono/stereo S16_LE at 48 kHz passes through
the linear rate converter to 96 kHz, then a routing table averages L/R into
native HFR slot 3. Mono is duplicated before averaging, so it retains its
level. Slots 0–2 stay silent. That original default PCM is playback-only
and has one client at a time.

Ram104 packages an isolated build of that upstream ALSA library with `dmix`.
Its [`asound-mix.conf`](asound-mix.conf) mixes clients at the native 96 kHz,
four-channel sink and retains the 48 kHz conversion and HFR slot-3 route.
Two overlapping silent application streams passed on the actual panel.
Stock ABE DSP effects remain separate. See
[the ram104 playback record](shared-playback-ram104.md) and
[the initial candidate trial](shared-playback.md).

`alsa-lib/` and `alsa-utils/` are unmodified upstream sources, pinned in
[`build_application_audio.py`](build_application_audio.py). They use the
same Cortex-A9 musl compiler and ABI as Qt. The shared library, standard
ALSA configuration tree, `aplay`, custom configuration and licenses are
packed into the RAM image. Rebuild with:

```sh
python3 development/audio/build_application_audio.py
# Then rebuild/stage the Qt app as described in ../perrier-qt/README.md.
python3 development/audio/test_conversion.py
```

The conversion test executes the actual ARM library and `aplay` under
QEMU, replacing only the hardware sink with ALSA file/null. Six cases check
mono unity gain, stereo averaging, half-level left/right, opposite-phase
cancellation, full-scale headroom and silence in all other hardware slots.
The immutable report is copied into each source snapshot.

In the RAM environment ordinary applications use the default ALSA PCM:

```sh
aplay -D default application-48k.wav
```

Qt now owns the native mixer. Its slider maps 0–100% to right-handsfree
gain values 0–24, capped at the observed stock setting. Volume zero or mute
selects the HFR route's Off state; unmute restores HF DAC and the selected
gain. Left handsfree and EP remain off. Every control write is read back;
failure is shown as an error. Original mixer values restore on normal exit.
The front keys retain hold-repeat for volume and one toggle per mute press.

The Qt test button plays bounded, faded, low-level 660 Hz beeps as a mono
48 kHz S16_LE stream on a nonblocking worker. Explicit 1,024-frame periods
and a 4,096-frame application buffer avoid the unresolved period-time
interval encountered with `snd_pcm_set_params()`. The exact setup function
is shared with a silent diagnostic and tested on the panel and under QEMU.
The initial error, RAM-only app fix, successful 30-second playback and
independent hardware/mixer samples are preserved in the ram98 run. No
display reset was used; only Qt was cleanly restarted to deploy that fix.

Production power management and stock DSP processing remain separate work.
No PMIC voltage policy changed here.
