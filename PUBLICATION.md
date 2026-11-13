# Public source repository and rebuild inputs

The public repository is [mcirsta/cisco-touch10-linux](https://github.com/mcirsta/cisco-touch10-linux).
It publishes the Touch 10 / Perrier board-support sources, ordered kernel
patches, device trees, configuration, diagnostic app, host tools and research
notes. Start with [README.md](README.md), then
[development/kernel/README.md](development/kernel/README.md).

Compiled kernel images, object files, initramfs archives and staged target
runtimes are excluded from Git. Device access keys, raw device backups,
stock firmware, extracted filesystems, private run captures and unrelated
reference checkouts also stay local. The root `.gitignore` defines the
publication boundary. Links in historical notes may point into those omitted
local directories; recorded absolute paths describe the original workspace.

## Kernel source and patch verification

Clone the repository and run commands from its root:

```sh
git clone https://github.com/mcirsta/cisco-touch10-linux.git
cd cisco-touch10-linux
```

Supply the pristine upstream `linux-6.18.48.tar.xz` archive at
`development/sources/linux-6.18.48.tar.xz`. Its expected SHA-256 is
`5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c`,
also recorded in [the source manifest](development/kernel/patches/manifest.json).
The archive is an external input, not a Git artifact. Verify the canonical
source overrides and patch application with Python 3 and `patch`:

```sh
python3 development/kernel/prepare_source.py --verify-only
```

Without `--verify-only`, that script also unpacks the pristine tree into
`development/kernel/work/`, installs the recorded overrides, and checks for
unrecorded source changes. Kernel compilation uses Clang/LLVM. Selected DT
schema checks additionally need `dtschema`; installation instructions and
the checks' scope are in the kernel README.

## Qt, userspace and toolchain inputs

The target ABI is ARMv7 hard float, Cortex-A9, NEON and VFPv3. Place these
archives under `development/perrier-qt/downloads/`:

| Archive | SHA-256 |
| --- | --- |
| `qtbase-everywhere-src-6.12.0.tar.xz` | `a951bd163c7b80fc6b8c88d7668fb56abf91c152373e13c10666763238131307` |
| `qtdeclarative-everywhere-src-6.12.0.tar.xz` | `311f3a2603e1973bb59baef9dfa740a376de713157d4782ee043681e889c9260` |
| `armv7-eabihf--musl--stable-2026.08-1.tar.xz` | `9147bafae4aa272321a3c6440d04d83b7e23411b2d344f875541d84c4444ba9b` |

[`prepare_sources.py`](development/perrier-qt/prepare_sources.py) verifies
these archives and the included Qt time64 patch before preparing them.
The build needs CMake, Ninja and compatible host Qt tools under `/usr`.
The [Qt README](development/perrier-qt/README.md) describes the build,
runtime staging and QEMU Cortex-A9 preflight. Ninja uses its default
parallelism.

The ALSA build also expects upstream Git checkouts at
`development/audio/alsa-lib` and `development/audio/alsa-utils` at commits
`f44e0abd5382f519cc6fa69850c34e6e9c09d5f5` and
`f3537ede21d0bc5b34835988752523b08459c532`, respectively.
[`build_application_audio.py`](development/audio/build_application_audio.py)
verifies those commits and rejects tracked source changes. It uses autotools
and the same Bootlin compiler. The [audio README](development/audio/README.md)
records the upstream projects, TinyALSA pin and conversion checks.
[`build_tools.py`](development/perrier-ramenv/build_tools.py) records the
separate BusyBox, Dropbear and strace archive hashes for RAM tools. Small
early-init tools also use Zig 0.15.2 as described in the existing workflow.
The preparation scripts expect these inputs to exist locally; they do not
download them automatically.

## Complete image build from a clean clone

Build the latest profile, ram116, with:

```sh
python3 development/standalone/build.py
```

The [standalone guide](development/standalone/README.md) lists the host
dependencies and output paths. This entry point fetches pinned upstream
inputs, compiles Qt, the app, ALSA and RAM tools, assembles a new initramfs,
then builds and audits the kernel and board DTB. It reads no earlier profile
images, root filesystems, private access configuration or live-test records.
The previously unexported ram116 CPU-voltage driver is now a versioned source
patch, and the kernel configuration is a versioned text input.

SSH is disabled unless a public key is supplied with `--authorized-key`;
that option generates a new image host key. The external Bootlin compiler,
its target runtime libraries and gdbserver are fetched upstream inputs.
The font comes from the host's DejaVu package. These are not old project
build products.

Historical incremental generators, including
[`build_image.py`](development/kernel/build_image.py), still describe their
original staged experiments and retain their historical prerequisites. Use
the standalone entry point for a complete ram116 build.

At the owner's request, local cleanup deletes source-built binary outputs
except the two newest complete profile directories:

| Retained local profile | Kernel identity |
| --- | --- |
| `development/perrier-ramenv/cpu-dvfs-low-trial/` | `6.18.48-perrier-ram115` |
| `development/perrier-ramenv/cpu-dvfs-mid-trial/` | `6.18.48-perrier-ram116` |

Those retained binaries remain excluded from Git. Source, patches,
configuration and records are preserved. Older reviewed image payloads and
compiled helpers are no longer kept merely because later scripts check
their hashes. The existing build chains therefore need their removed
dependencies reconstructed before they can run again. ADC RAM trials also
require reconstruction and verification of the compiled postflight helper
against its recorded approval before use.

The standalone builder reconstructs the required image inputs from source.
Its audits check the fresh image, including its embedded initramfs and RAM
safeguards. Hardware qualification remains a separate step. Historical image
hashes and test results identify the tested artifacts; a new build is not
claimed to be byte-identical.

The [clean-clone verification record](development/standalone/validation-clean-clone.json)
documents a complete host rebuild with fresh upstream downloads, 43 passing
tests, Cortex-A9 Qt execution checks and a passing kernel/rootfs audit.

Publishing the sources does not authorize device writes. Current recovery
work remains read-only investigation, apart from the explicitly recorded,
bounded ADC postflight restoration. Consult [AGENTS.md](AGENTS.md) and the
[development workflow](DEVELOPMENT-WORKFLOW.md) before device work.

## Validation of the published source snapshot

The following command passed all 16 host-tool tests in a fresh source-only
snapshot. The runner tests create temporary fixture payloads rather than
depending on local kernel or device binaries:

```sh
python3 -m unittest discover -s tools -p 'test_*.py'
```

These seven direct kernel-source tests also passed in that snapshot:

```sh
mkdir -p development/kernel/out
python3 development/kernel/tests/test_bridge_regmap.py
python3 development/kernel/tests/test_core.py
python3 development/kernel/tests/test_dsi_power.py
python3 development/kernel/tests/test_dsi_timing.py
python3 development/kernel/tests/test_dsi_vc.py
python3 development/kernel/tests/test_i2c.py
python3 development/kernel/tests/test_pcf_shutdown.py
```

Historical DTB and image audit tests require removed profile artifacts to
be rebuilt first. `test_dsi_null.py` additionally requires an include header
from the unpacked pristine Linux source. Those tests are outside the passing
source-only checks above; this publication does not claim a passing complete
image test suite or a newly qualified device build.

## Licensing and provenance

Keep existing copyright, SPDX and license notices with all copied or
modified sources. Kernel code, Qt and upstream userspace components retain
their respective licenses. This repository does not impose a new blanket
license on those components. Stock firmware and device backups are excluded
from this publication; their presence in the private workspace is not a
redistribution grant.
