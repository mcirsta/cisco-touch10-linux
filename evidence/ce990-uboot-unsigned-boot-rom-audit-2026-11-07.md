# Exact CE9.9.0 U-Boot: unsigned boot and ROM-read audit

Date: 2026-11-07. This was **offline analysis only**. The Touch 10 was not
accessed and no U-Boot environment, firmware, or device storage was changed.
A later, separately authorized live test is recorded in
[the bootz proof](uboot-bootz-live-proof-2026-11-07.md).

Input: `firmware/codec-ce9.9.0/extracted/u-boot_signed.bin`, SHA-256
`9550311050968123a53d7c0be6aa309d1c3b8629515aa0eaddebba628fb161d5`.
The U-Boot code is extracted from file offset `0x390` (912) into
`firmware/codec-ce9.9.0/analysis/touch10-ce990-uboot-code.bin`, loaded at
`0x80e80000` as ARM Thumb in the corresponding `.i64` database. The saved
eMMC partitions 6 and 7 match the exact package; see the root SSH and
recovery audit.

## Registered command table and dispatcher

The command table occupies `0x80eaca88`–`0x80ead1dc` in 28-byte entries,
67 entries total. The lookup at `0x80e87bf0` searches this table. The
dispatcher at `0x80e880b0` reads the handler pointer from each matched
entry's `+0x0c` field and calls it at `0x80e8810c`. In this path, it checks
argument count and bootd recursion, but has no general secure-mode gate.

Relevant table entries (name, entry, handler):

| Command | Table entry | Handler | Finding |
| --- | --- | --- | --- |
| `go` | `0x80eacd7c` | `0x80e829c4` | Handler is only `MOVS R0,#1; BX LR`. The apparent arbitrary-address jump command is disabled in this build. |
| `bootm` | `0x80eacb14` | `0x80e82bfa` | Legacy uImage path invokes Cisco certificate and SHA-1 verification. |
| `booti` | `0x80eacaf8` | `0x80e83098` | Partition boot path invokes the same verification for its legacy wrapper. |
| `bootz` | `0x80eacb4c` | `0x80e833e8` | Raw ARM zImage path checks the zImage magic and proceeds to Linux startup without the Cisco verifier in its traced path. |
| `source` | `0x80ead118` | `0x80e86f48` | Executes a legacy U-Boot script image from memory after `0x80e86eb8` checks magic, header CRC, optional data CRC, and script type; no Cisco certificate call appears in this path. |
| `md` | `0x80eacf04` | `0x80e85956` | Displays bytes/words from a supplied memory address; no address-range check appears in this handler. |
| `cp`, `crc32` | `0x80eacba0`, `0x80eacbbc` | `0x80e85af4`, `0x80e85b44` | Registered memory-copy and checksum commands, possible read probes only if the memory region is accessible. |
| `loadb`, `loads`, `loady` | `0x80eace78`, `0x80eace94`, `0x80eaceb0` | `0x80e8534c`, `0x80e852bc`, `0x80e8534c` | Serial transfer into RAM is registered. |

Thumb handler addresses in table entries have bit 0 set; even addresses above
are the actual instructions. The table has `fatload`, `ext4load`, `tftpboot`,
and `dhcp` as other RAM-load routes.

The secure-mode warning has a narrow call site. `0x80e825d8` only prints
`Unit is in secure mode, no operations are allowed` and returns zero. The
main loop calls it after a key interrupts a positive `bootdelay` countdown
(`0x80e8cda8`), then resumes boot. The same main loop branches directly to
the command loop at `0x80e8ce64` for `bootdelay=-1`, or after `bootcmd`
returns. The live device has an invalid environment CRC and therefore uses
compiled defaults with no `bootdelay`, so the current serial Ctrl-C route
does not reach the prompt. A valid environment could change this behavior,
but that is not yet tested on the panel.

## Verification boundaries

The `bootm` legacy uImage path checks image magic, header CRC, data CRC,
then calls `0x80e82866` at `0x80e82ccc`. That routine calls
`0x80e824d4`, which uses the OMAP ROM entrypoint for certificate signature
selector `0x0c` and SHA-1 selector `0x3e`, compares the digest, and reports
`certificate signature failed` or `SHA1 hash mismatch` on failure. The
`booti` legacy-image path calls the same routine at `0x80e831f2`. A simple
unsigned legacy kernel uImage is therefore not an established boot route.

`bootz` is materially different. At `0x80e83426`, it calls
`0x80e820c0`, which checks the ARM zImage magic `0x016f2818` at image
offset `0x24` and reads the start/end fields at `+0x28`/`+0x2c`. The
`bootz` path then handles optional initrd/FDT and calls the kernel startup
routine; it contains no call to `0x80e82866` or `0x80e824d4`. An optional
legacy initrd or FDT can still be checked by the generic image helpers. With
a plain zImage and no optional images, the traced boot path is an unsigned
RAM-boot candidate. The later live test booted a modified zImage through this
path; see the linked proof above.

`source` is another command-execution candidate. Its handler parses a legacy
script uImage at a supplied RAM address. The source validator
`0x80e86eb8` checks magic, header CRC, type 6 (script), and data CRC when
`verify` is enabled; it does **not** call the Cisco certificate verifier.
The compiled default environment has `autoupgrade=0`, but its `bootcmd`
contains `run upgradenetwork` when `autoupgrade=1`, and
`upgradenetwork=if usb start; then if dhcp 0x82000000 /touch10.bootscr; then
source 0x82000000; ...`. This would fetch and run a CRC-valid script from a
DHCP/TFTP server if U-Boot's USB Ethernet initialization and the network
request succeed. The binary contains SMSC95xx USB Ethernet support and a
`scanning usb for ethernet devices` message, but this path has not been
live-tested. A signed software package is not involved in `source` itself.
If this network route works, the script could invoke `md` or load and invoke
`bootz` without an interactive prompt. It still requires a deliberately
constructed valid environment and a controlled reboot.

## Boot ROM read possibility

The registered `md` command is the simplest U-Boot-side read candidate. Its
handler parses a user-supplied address and passes it to the memory-display
routine without a visible range restriction. This makes `md` a possible
way to read physical `0x40030000`–`0x4003bfff` over the serial console **if**
the ROM is bus-readable from U-Boot's execution state. `cp` could move
accessible bytes to RAM, and `crc32` could test a bounded range. None of
these commands has been run on the ROM. The previous Linux `/dev/mem` read
faulted in a reserved region because it used the wrong address; it offers no
evidence about ROM access. U-Boot access must not be assumed; a ROM read
could hang or reset the unit. A successful unsigned `bootz` jump likewise
does not by itself prove that its payload can read secure ROM.

## Practical order of operations

1. Prepare a reversible, verified way to reach a U-Boot command, using the
   known single-copy environment in partition 8. Preserve the compiled
   normal `bootcmd` and arrange restoration before any console experiment.
   The earlier recovery audit describes a proposed self-restoring command;
   its parsing and save behavior still need offline validation.
2. Confirm `TOUCH10> ` and `help bootz`, `help md`, and `help source` on the
   panel before attempting a ROM read or unsigned boot.
3. If the console works, use a tiny bounded memory read before any 48 KiB
   dump. Treat an abort as a stop condition.
4. For unsigned code execution, load a plain zImage into RAM by serial or
   USB Ethernet/TFTP and use `bootz`; keep storage untouched for the first
   execution test. The alternate script route is `source` of a CRC-valid
   U-Boot script that loads and invokes `bootz`.

An [offline console environment image](uboot-console-candidate-2026-11-07/README.md)
was subsequently built from the exact defaults and independently checked for
size, CRC, variable layout, and package identity. The owner then authorized
one live test. It reached the command prompt and booted a two-byte modified
zImage through `bootz`; see the [live proof](uboot-bootz-live-proof-2026-11-07.md).
Boot ROM readability remains untested from U-Boot.
