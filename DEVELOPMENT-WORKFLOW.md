# Touch 10 development workflow

After the source publication cleanup, only the ram115 and ram116 compiled
profile directories remain locally. Older images and compiled userspace
helpers must be rebuilt before running the historical workflows below.
See [publication and rebuild notes](PUBLICATION.md).

The active source and build entry points are in
[development/kernel](development/kernel/README.md). Kernel trials boot
through the installed U-Boot. Qt and userspace iterations use the running
RAM environment over SSH without a kernel reboot. The current qualified
default is `native-diagnostics` ram100, with `speaker-audio` ram99 as fallback.

## Build and review

From `/home/marius/ext_proj/touch10`:

```sh
python3 development/kernel/build_image.py
python3 development/kernel/audit_image.py
python3 development/kernel/check_sources.py
```

Edit canonical files under `development/kernel/source/`. The build exports
ordered subsystem patches, verifies clean application against the pristine Linux
6.18.48 archive, and rejects unrecorded source edits. The audit checks the
DT physical addresses and board wiring against the saved ram65 baseline, packed and embedded
initramfs files, configuration, driver tests and the unchanged watchdog
feeder. The bus auditor also rejects ten unsafe DT mutations. Review `development/kernel/patches/series` and the audit output
before booting a candidate.

The source checks use workspace-local `dtschema` tools, falling back to `PATH`; see the active
workspace README for setup and the validation scope.

The native-diagnostics profile requires its approved, hash-pinned ADC
postflight helper before arming. After healthy stock return, the controller
restores three sensing controls and verifies readback. The owner's standing
authorization is recorded in AGENTS.md and the ADC approval JSON; other
recovery changes retain their existing scope. Carry this cleanup into any
later profile that keeps the ADC enabled.

## U-Boot RAM trial

```sh
python3 tools/touch10_dev.py doctor
python3 tools/touch10_uboot.py prepare --profile native-diagnostics
python3 tools/touch10_uboot.py session --profile native-diagnostics --minutes 60
```

`prepare` creates and audits a fresh one-use candidate on the PC. `session`
stages two immutable, verified image files under the stock data partition,
writes and reads back the reviewed 256 KiB one-shot p8 environment once,
then software-reboots. U-Boot saves the exact factory boot command before
loading the kernel. MLO and U-Boot are not replaced. A fresh prepare is
required for every attempt.

The default `display-stop-fix` profile selects validated ram93: pristine
DISPC/DSS, mainline sync/clock/porch/pad configuration, generic PHY phases
and bridge-requested HS clock after reset release. The stopped video VC
remains disabled while the dedicated command VC is available. It passed
six display/Qt restarts without host display errors, physical touch and
brightness checks, and watchdog recovery. Its frozen source is under
`development/kernel/baselines/ram93`. The active
builder may target a later experiment; use its explicitly reviewed profile.
See [the comparison](development/kernel/display-reduction.md).
The preserved ram70 fallback is `--profile display-onoff`; ram69 is
`--profile display-pll-only`.
Ram66 remains available as `--profile mainline-bus`, ram65 as
`--profile mainline-ram`; ram64 is
`--profile gen4-touch`. Earlier
profiles remain available for diagnostics. The RAM kernel makes eMMC
read-only and mounts no eMMC filesystem.

The session waits for RAM SSH, verifies the restored factory environment,
starts Qt and renews the watchdog lease. Logs and `result.json` live in a
private directory under `development/runs/`. The runner serializes trials
with `development/.runner.lock` and stops after a failed recovery.

## Work in the running RAM environment

```sh
ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram
python3 tools/touch10_ram.py status
python3 tools/touch10_ram.py recover
```

Use the existing RAM upload/Qt helpers for rebuilt userspace binaries.
The key-only SSH connection uses a separate pinned RAM host key. Neither a
panel root password nor a host sudo password is needed for ordinary runs.

The kernel enables the mainline OMAP watchdog early with a 120-second
nowayout timeout. The unchanged RAM guard feeds it every five seconds while
its host lease remains valid. `recover` requests a normal return to stock;
`recover --hardware` deliberately stops feeding to test hardware recovery.
Keep the controlling session alive until it reports `STOCK_RECOVERED`.
Recovery verification checks a new stock boot ID, Linux 3.4.113+, Phoenix,
and p8 SHA-256 `f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.
An early hang before watchdog initialization may still require a physical
power cycle. A full physical power-removal test of the complete image is
still pending; the minimal image already passed that test.

## Host setup and earlier qualification

The dedicated NetworkManager profile `touch10-direct-isolated` uses
`enp7s0` at 10.77.10.1/24 without a default gateway. The installed
`touch10-dev-dhcp.service` leases 10.77.10.10 only to this panel and supplies
no DNS/default route. The exact-serial-number UART udev rule grants desktop
access. Setup files are in [development/host](development/host/).

On another PC the installer needs host administrator authentication once:

```sh
sudo bash development/host/install.sh
```

The earlier kexec, closed-file-descriptor watchdog and U-Boot qualification
records remain in the [historical workflow](development/archive/DEVELOPMENT-WORKFLOW-before-kernel-cleanup.md),
[watchdog evidence](evidence/kexec-watchdog-recovery-2026-11-08.md),
[one-shot boot record](development/perrier-coldboot/README.md) and
[Ethernet boot record](development/perrier-cold-ethernet/README.md).
Kexec remains available for specific diagnostics.
