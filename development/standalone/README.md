# Build ram116 from a clean clone

This entry point builds the `cpu-dvfs-mid-trial` RAM image,
`6.18.48-perrier-ram116`, without a previous project binary, root filesystem,
image manifest or device backup. It fetches pinned upstream inputs, builds
Qt and the application, builds ALSA and the RAM tools, assembles a new
initramfs, and compiles and audits the kernel and board DTB.

From a new checkout:

```sh
git clone https://github.com/mcirsta/cisco-touch10-linux.git
cd cisco-touch10-linux
python3 development/standalone/build.py
```

The build runs on the host. It does not contact, reboot or flash a panel.

## Host requirements

Use an x86-64 Linux host with Python 3.12 or newer and these development
tools installed:

- Clang/LLVM, including `clang`, `clang++`, `ld.lld`, `llvm-ar` and
  `llvm-objcopy`; GNU Make and `cpp`.
- CMake, Ninja, `pkg-config`, Git and `patch`.
- Autotools, including `autoreconf`, Automake, `libtoolize` and gettext's `autopoint`;
  Bison, Flex and `gperf`.
- Qt 6.12 host development tools under `/usr`, including Qt Declarative and
  ShaderTools build tools. `pkg-config` must report `6.12.x` for `Qt6Core`,
  `Qt6Qml` and `Qt6ShaderTools`.
- QEMU user-mode ARM emulation, providing `qemu-arm`.
- DejaVu Sans and its license. Standard Arch and Debian font locations are
  detected; `PERRIER_FONT` and `PERRIER_FONT_LICENSE` select custom paths.

Check the command dependencies and host Qt version before downloading:

```sh
python3 development/standalone/build.py --check-host
```

The first build also needs network access and space for the upstream source
trees and compilation outputs. Ninja uses its default parallelism.

## Inputs and outputs

[`inputs.json`](inputs.json) records the exact release URLs, archive hashes
and Git commits. It covers Linux 6.18.48, Qt 6.12.0, BusyBox, Dropbear,
strace, ALSA and the Bootlin ARMv7 hard-float musl toolchain. Archives are
verified before extraction, and Git sources must match their pinned commits.

The Bootlin compiler is an external prebuilt build dependency. Its target
C/C++ runtime libraries and `gdbserver` are also upstream inputs from that
verified archive. DejaVu Sans comes from the host font package. These inputs
are distinct from this project's kernel, Qt installation, application,
ALSA, RAM tools and helpers, which are built afresh. No old project output
is fetched or used as a fallback.

The default output directory is `development/standalone/out/ram116/`:

| Output | Purpose |
| --- | --- |
| `kernel-build/arch/arm/boot/zImage` | Newly compiled ARM kernel with the embedded initramfs |
| `board.dtb` | ram116 board configuration |
| `initramfs.cpio` | Newly assembled RAM root filesystem |
| `build.json` | Stage results and input/host records |
| `kernel-build.json` | Kernel, DTB, configuration and embedded-initramfs audit |
| `rootfs-build.json` | Rootfs source records and audit |
| `logs/` | Userspace build logs |
| `kernel-build.log` | Kernel compilation log |

`--output PATH` selects another output directory. Build outputs stay out of
Git; source files, templates and configuration remain versioned.

## Optional SSH access

Without an explicit public key, SSH is disabled in the image. To authorize
your public key while assembling it:

```sh
python3 development/standalone/build.py --authorized-key ~/.ssh/id_ed25519.pub
```

The builder accepts an OpenSSH public key, generates a new image host key,
and writes `known_hosts` beside the output reports. It does not import
`access/`, an existing private key, or a previous image's SSH identity.
Keep that image and its output directory private because they contain the
new host private key.

This remains a bounded RAM test image. The mainline hardware watchdog uses
a 120-second timeout. The freshly compiled guard starts with a 90-second
boot grace period; later renewals extend its host lease by 60 seconds, so
the controller must renew before that lease expires.
The build does not renew that lease. eMMC writes are forced read-only and
the startup script mounts only pseudo-filesystems.

## Cache and stage resume

An optional cache can supply verified original upstream archives rather
than downloading them again:

```sh
python3 development/standalone/build.py --cache /path/to/upstream-inputs
```

The cache uses archive filenames from `inputs.json`. Pinned Git source
bundles may also be provided as `<name>-<full-commit>.bundle`; these contain
upstream Git source, not built executables or installations. `--offline`
requires every selected input to be present locally or in that cache.
The cache never supplies a historical project kernel, rootfs, Qt install
or other compiled project output.

Individual stages can resume work in the same clone:

```sh
python3 development/standalone/build.py --stage inputs
python3 development/standalone/build.py --stage userspace
python3 development/standalone/build.py --stage rootfs
python3 development/standalone/build.py --stage kernel
```

Later stages require the earlier stages' fresh results. Stage resume is a
development convenience; it is not a new clean-clone verification. Pass
`--authorized-key` again when resuming `rootfs` if SSH should be enabled.

## Host validation

The [clean-clone validation record](validation-clean-clone.json) records a
complete ram116 rebuild on 13 November 2026 using fresh upstream downloads.
All 27 standalone tests and 16 existing host tests passed. Both the staged
and packaged Qt app passed Cortex-A9 QEMU start/exit checks, and the fresh
kernel passed its static image audit. Optional SSH key/host-key generation
was also exercised without a device connection.

Run the standalone builder tests and the existing host-tool tests with:

```sh
python3 -m unittest discover -s development/standalone/tests -p 'test_*.py'
python3 -m unittest discover -s tools -p 'test_*.py'
```

A successful full build records `built-and-audited` in `build.json` and
checks the resulting kernel, DT wiring, RAM safeguards and embedded rootfs.
These are host-side checks. The rebuilt image has not thereby passed a
hardware boot, display, touch, audio or recovery trial; reports retain
`live_tested: false` until a separate authorized device validation.
