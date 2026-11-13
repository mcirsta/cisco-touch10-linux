# Touch 10 root SSH and recovery audit, 2026-11-07

This audit predates the separately authorized one-time U-Boot console and
`bootz` test. The live outcome is in
[the bootz proof](uboot-bootz-live-proof-2026-11-07.md).

## Live root SSH status

On the direct `10.77.10.1` to `10.77.10.10` link, the already demonstrated
temporary root path was reopened. A dedicated ECDSA P-384 key was installed
for the stock OpenSSH server. The release-build SSH marker is
`/user/start_ssh`; `/config/sysconfig/rootsettings` contains
`ROOTSETTING=on` with a locked password hash (`ROOTPW='!'`). The root login
override and authorized key are restored into the RAM root filesystem by
`/user/root-access/boot.sh`, sourced from the persistent
`/config/sysconfig/hostname` file. The original hostname file is preserved as
`/user/root-access/hostname.before`.

The stock `S20sshd` script initially failed because it created `/var/empty`
with mode 775, which OpenSSH rejects. The boot hook now creates it with mode
755 before `S20sshd` runs. A live test deleted the two volatile login files,
sourced the hook, and confirmed that it restored them and that `sshd -t`
passed. Sourcing the exact `/etc/profile` startup path after committing the
hook also passed. A separate SSH connection returned `uid=0(root)`. The host key was
pinned in `access/known_hosts`; its RSA fingerprint is
`SHA256:Nx0xRoyvIu9VnP6layMeWfbLveFeklxU7KrAOSbNaxs`.

The owner then authorized one normal software reboot. Pre-reboot boot ID was
`fdd0d744-9b80-4a00-99a6-b74ea2e4dc3a`; post-reboot boot ID was
`ffe2bc7f-5ce5-44d6-801b-4818171b82c7`. The panel went offline and
returned. A fresh SSH connection returned `uid=0(root)`, with active image2,
the key and login gate restored, `/var/empty` at mode 755, `sshd -t` passing,
and the normal `phoenix` process running. The temporary root shell closed
during reboot. The temporary updater symlink and RAM script were absent on
the new boot. No signed firmware image or bootloader partition was modified.

## Root filesystem checks

U-Boot's normal boot log verifies checksums for the kernel and rootfs uImages.
The package installer verifies Cisco's signed update package before
installation. `/etc/init.d/S90file-system-verification` starts a script that
exits on products other than Carbon, Arctic, Asterix, and Drishti, so this
runtime verifier does not check the Touch 10 (`idefix`) image. The running
root filesystem is unpacked into RAM; changes to `/etc` alone do not survive
reboot. This SSH setup uses `/config` and `/user` rather than modifying the
signed rootfs image.

## Boot and recovery inventory

- GPT partition 1 (`isw`) contains an MLO byte-for-byte identical to the
  recovered CE9.9.0 package. Both signed U-Boot copies in partitions 6 and 7
  are also byte-for-byte identical to that package. The MLO tries those two
  copies in order, then a legacy location.
- The active system is `image2` on partition 14. `/mnt/base/image1` does not
  exist, and the starts of the nominal alternate kernel/system partitions
  lack a kernel image or filesystem header. There is no established usable
  automatic OS fallback.
- GPT partition 10 (`diag_system`) contains a uImage named
  `Perrier diagnostic 20171105`. Its header CRC and 26,010,448-byte data CRC
  both match. Inside it is an Android-style boot image with a 128 MiB ext2
  diagnostic ramdisk. Its `inittab` respawns `/bin/sh -l` on `ttyO2`, but its
  login profile starts a factory test CLI and `stdioSwitch`. Serial root
  access through that image has not been tested on this unit.
- The exact packaged U-Boot defaults to `diag_booting=0` and has no
  `bootdelay`. Its `bootcmd` uses `booti mmc 1 10 0x84000000` only if
  `diag_booting=BOOTING_DIAG_IMAGE`. The live boot reports a bad environment
  CRC and uses these defaults. The environment is at the start of partition 8;
  no boot selector was changed.
- The primary GPT header has a valid CRC. Its declared backup GPT header is
  absent, as is a header at the physical final sector. The unit boots from
  the primary table. The GPT has not been repaired.

The complete raw user-area, boot-area, and EEPROM backup predates these SSH
changes and is in `backups/touch10-2026-11-07`.

## U-Boot environment location, read-only confirmation

The exact CE9.9.0 signed U-Boot payload was extracted at file offset 912 from
`firmware/codec-ce9.9.0/extracted/u-boot_signed.bin` and analyzed as ARM32
Thumb at load address `0x80e80000`. In that binary, the MMC environment address
helper at `0x80e89a30` returns byte offset `0x08b60000`. The loader at
`0x80e89b48` reads `0x40000` bytes from MMC device 1 at that offset and passes
the buffer to the environment importer at `0x80e894e4`. The `saveenv` path at
`0x80e89a50` uses the same helper and writes the same span, after exporting
`0x3fffc` data bytes and a four-byte CRC. This is one environment copy in the
observed code; no redundant address was found in these paths.
The IDA database is saved as
`firmware/codec-ce9.9.0/analysis/u-boot-code.bin.i64`.

`0x08b60000 / 512 = 285440`, exactly the start sector of GPT partition 8,
`sb2-data`. Its length is 512 sectors, exactly `0x40000` bytes. Linux also
reports p8 start 285440 and length 512. The current p8 was read over the
verified root SSH connection and its SHA-256 matches the full-device backup:
`bd527afd42a26a7b983775d05c33c1860c879ef61f38da0c0329f92610839eca`.
Its only nonzero bytes are `58 58 58 58 0a` (`XXXX\n`) at the beginning. The
stored first word `0x58585858` does not match the CRC32 of the remaining
`0x3fffc` bytes (`0xcfe1dfea`), consistent with the observed bad-CRC boot
message and fallback to compiled defaults.

This identifies a confined environment area for a possible future recovery
experiment. It does not establish a tested, safe environment write procedure
or prove that diagnostic boot completes. No environment bytes were changed.
Because `diag_booting` is a persistent variable, simply setting it would
select the diagnostic image on every subsequent boot. Any later test would
need a separately verified way back to the normal boot command before the
first reboot; the diagnostic console alone is not yet a proven fallback.

## Diagnostic console, offline analysis only

The verified p10 diagnostic image contains an ext2 ramdisk. Its `inittab`
starts `/bin/sh -l` on `ttyO2`, which is the unit's service UART. However,
`/etc/profile` runs `/home/root/fox/idefix_cli.sh`, which starts the factory
CLI and then `stdioSwitch` in the foreground. The shipped
`/etc/stdioSwitch.ini` defines a `SHELL` client with
`cli_execute_pathname = "/bin/sh"`, `client_mode = "1"`, and blank login
fields. Static analysis of the bundled `stdioSwitch` ELF shows a `switch`
command accepting `SHELL`; the client-mode path goes directly to its active
state and launches the configured executable. This suggests a shell through
the diagnostic switch interface, but neither diagnostic boot nor that command
has been tried on this panel.
The extracted executable and IDA database are preserved in
`backups/touch10-2026-11-07/analysis/`; the executable SHA-256 is
`7e5f04bfd2d2f4974510aa5e449170bb4b6135195e4bf4bdf04e9a3e1a948f52`.

The visible diagnostic init scripts create device links and start hardware
services. They do not visibly mount an eMMC filesystem for writing, but the
factory CLI and helper binaries have not been fully audited for side effects.

## Can a valid environment expose U-Boot control?

Further disassembly of the exact U-Boot main loop at `0x80e8cd0a` shows that
it reads `bootdelay` from the imported environment. If the variable is absent,
it uses `-2`, skipping the countdown. A positive value displays `Hit any key
to stop autoboot` and polls console input. But a keypress calls
`0x80e825d8`, which always prints `Unit is in secure mode, no operations are
allowed` and returns to the normal boot-command path. Thus merely adding a
positive `bootdelay` would **not** expose a prompt on this build.

The same main-loop code sends `bootdelay=-1` directly to its command loop at
`0x80e8bc74`, without running `bootcmd`. The command loop contains the
`TOUCH10> ` prompt and serial input parser. Also, if a `bootcmd` completes and
returns, control falls into that command loop. These are static paths to an
interactive U-Boot console, not live-tested behavior. A persistent `-1` would
stop normal boot on every cycle and would be risky if the console is unusable.

For a future controlled experiment, a candidate environment could preserve
the entire compiled default environment, store its normal `bootcmd` under a
separate variable, and use a temporary command that restores and saves the
normal boot command *before* returning to the prompt. That would need offline
construction and verification of the exact CRC, script quoting, and fallback
behavior, followed by explicit owner authorization before writing p8. No
environment image was written to the panel during this investigation.

One possible script shape, **not yet executed**, is to set `normalboot` to the
original factory `bootcmd` and use
`bootcmd=setenv bootcmd run normalboot; if saveenv; then echo CONSOLE; else run normalboot; fi`.
On the successful path, U-Boot would first save a normal boot command, then
return to its command loop; a later power cycle should therefore boot normally.
On a reported save failure, it would attempt the original boot immediately.
Actual behavior and parsing need verification before treating this as a
recovery procedure.

The compiled default environment contains 25 NUL-separated variables, is
`0xa3c` bytes long, and has no `bootdelay`. A hypothetical copy with only
`bootdelay=-1` added fits the `0x3fffc`-byte data area; standard CRC32 over the
zero-padded data would be `0x4ee27b1f` (little-endian header bytes
`1f 7b e2 4e`). This was calculated offline to check the format, not written.
