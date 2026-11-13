# CE9.9.0 local escalation audit (2026-11-07)

This is offline analysis of the matching Touch 10 factory package
`firmware/codec-ce9.9.0/idefix.pkg`, not a raw dump of this unit's eMMC.
`extracted/vcinfo.txt` identifies revision `46f7ea38fda`; the package kernel's
embedded version string exactly matches the live serial boot log in
`evidence/console-inventory.log`: Linux `3.4.113+`, build time 2019-09-17,
compiler GCC 8.3.0. No exploit code was run on the panel for this audit.

## Kernel

The package's `extracted/kernel` is a uImage. Its zImage contains a gzip
member starting at byte 17,451. Decompressing that member revealed an
`IKCFG_ST`/`IKCFG_ED` compressed kernel configuration. The exact recovered
config is `evidence/ce990-kernel-config-2026-11-07.txt` (71,511 bytes).

Relevant options: `CONFIG_NAMESPACES` off (therefore no user namespaces),
`CONFIG_KEYS` off, `CONFIG_IP_DCCP` off, `CONFIG_PACKET=y`,
`CONFIG_PERF_EVENTS=y`, `CONFIG_NETFILTER=y`, `CONFIG_DEVMEM=y`,
`CONFIG_SMP=y`, and `CONFIG_PREEMPT=y`. The kernel's configuration does not
establish its Cisco patch set. It does rule out keyring and DCCP bug families
at the subsystem level.

The upstream 3.4.113 release includes the `mm, gup: close FOLL MAP_PRIVATE
race` change for Dirty COW (CVE-2016-5195). A Cisco fork could in principle
diverge, but an exploit based only on an older 3.4 version number is not
justified. AF_PACKET flaws such as CVE-2016-8655 require `CAP_NET_RAW`; the
installed build has no user namespaces for acquiring that capability, and
the `support` console has not shown it. CVE-2017-1000112 (UFO) likewise
requires special interface/socket conditions normally obtained with user
namespaces or `CAP_NET_ADMIN`. No kernel exploit is confirmed or prepared.

## glibc and setuid programs

The exact rootfs contains `libc-2.29.so`; running `libc.so.6` under QEMU
prints GNU C Library 2.29. That excludes the glibc `GLIBC_TUNABLES` overflow
CVE-2023-4911, introduced in 2.34. The 2026 `$ORIGIN` dynamic-loader flaws
cover 2.29 by version but require a setuid/setgid executable with a specific
`$ORIGIN` RPATH or RUNPATH. The package has only two such executables in its
SquashFS metadata: `extra.img/bin/sudo` and
`extra.img/libexec/dbus-daemon-launch-helper`. `sudo` has RPATH
`//libexec/sudo`; the helper has no RPATH/RUNPATH. Neither has the required
`$ORIGIN` path. CVE-2024-2961 requires conversion to ISO-2022-CN-EXT; no
gconv module for that encoding was found in the extracted images.

The same SquashFS metadata marks `sudo` setuid root. Its binary embeds
version **1.8.21** and was built in 2019. That version is in the published
range for CVE-2021-3156 (Baron Samedit), a local root escalation through
`sudoedit -s`. This is a meaningful *second stage* if we obtain arbitrary
unprivileged command execution, although Cisco's exact patch state and ARM
exploitability have not been proved. The restricted console cannot invoke
`sudoedit -s`: its `selectsw` handler constructs `sudo selectsw <arguments>`,
and `sudoers.d/support` permits only `reboot`, `selectsw`, and
`remotesupportuser` as root.

## Bash, BusyBox, and the service console

The exact rootfs `/bin/busybox` prints **1.28.2**, and `/bin/sh` points to
`bash`, which prints **3.2.57**. The classic Shellshock environment payload
was tested against this exact Bash binary under QEMU: it printed only the
intended marker, and a `BASH_FUNC_x%%` import attempt was rejected. This
does not audit every shell parser path, but the famous Shellshock route is
not reproduced. The BusyBox `awk`/`hush` vulnerabilities do not apply to the
restricted console's exposed command map; `netstat` is the BusyBox applet it
can launch, and BusyBox is not setuid.

IDA analysis of the exact `apps.img/bin/supportsh` at `0x1a24` and
`handle_os_command` at `0x269c` confirms a fixed command map. It reads at
most 1,023 input bytes with `fgets`, copies the first token to a 1,024-byte
global buffer, and allows only alphanumerics, whitespace and a small
punctuation set in arguments before constructing `bash -l -c` for mapped
commands. The single quote character is allowed, but no shell command
separator, command substitution, or backtick is allowed. An argument can
alter shell quoting, yet no executable escape from the fixed `ip`, `netstat`,
or `sudo selectsw` prefixes is established. Any execution through `ip` or
`netstat` would inherit the unprivileged `support` account, so a second
escalation would still be required.

## GhostLock and a second console pass

GhostLock (CVE-2026-43499) is a credible *local* kernel lead for this panel.
The matching kernel configuration has `CONFIG_FUTEX=y` and
`CONFIG_RT_MUTEXES=y`, and the 2019 build predates the 2026 fix. In upstream
Linux 3.4.97, `remove_waiter()` clears `current->pi_blocked_on`, while
`rt_mutex_start_proxy_lock()` calls it when a proxy lock attempt fails. The
3.4 futex implementation includes `FUTEX_WAIT_REQUEUE_PI` and
`FUTEX_CMP_REQUEUE_PI`. These are the components of the published GhostLock
bug. This is stronger evidence than kernel version alone, but we have not
located the exact functions in Cisco's compiled kernel or tested the syscall
sequence on the panel. The older kernel does not expose a separate
`CONFIG_FUTEX_PI` line in its recovered configuration, so that modern
configuration name should not be used as a negative check here.

The published full exploit is tailored to modern x86 kernel layouts. A
separate researcher reports an ARM32 port on Linux 5.4, showing that ARM32
is possible but not that its offsets, stack reclaim, or code-execution step
will work on this OMAP 3.4 build. Linux 3.4 also uses a different scheduler
API for the PI chain walk. A local ARM program and board-specific work would
still be needed. GhostLock cannot be fired from the `supportsh` command list
by typing a shell command; it is a second stage after we can execute a
program as `support`.

I decompiled all file-reader handlers of the exact CE9.9.0 `supportsh`:
`show`, `head`, and `tail` call `process_files()`, which resolves only the
six static log aliases; `tailf` resolves the same map and caps its file
descriptor list at 16. Each console line is capped at 1,023 bytes, and the
two 1,024-byte global token buffers are adjacent but distinct; the apparent
`buf.9038 + 0x400` access in the decompiler is the start of the second
buffer, not an overflow. `bootlogo` accepts exactly `on` or `off` for its
write path. An `historiclogs`/`scp` handler exists in the binary, but it is
absent from the command-dispatch table and cannot be selected by name.

I also extracted the exact CE9.9.0 rootfs `bin/selectsw` to
`firmware/codec-ce9.9.0/analysis/touch10-ce990-selectsw`. The support
console invokes it through `sudo`, so it runs as root, but its supplied
image name is quoted in file tests and hook calls. An image switch updates
the persistent `active` symlink and may call `upgradebootsw`; it is not a
safe execution or backup primitive. The exposed `ip` and `netstat` commands
still have no established execution path; the earlier live `ip netns exec`
and `ip vrf exec` probes failed. This pass found no demonstrable console
escape or memory corruption in the mapped handlers.

A later exact-binary memory audit found two availability defects in those
handlers: multi-file `show`/`head`/`tail` input can loop indefinitely, and
`tailf` can close an uninitialized descriptor slot after an early open
failure. Neither has yielded an out-of-bounds write, command execution, or
root access. Details and off-device traces are in
`evidence/ce990-supportsh-memory-audit-2026-11-07.md`.

## Practical sequence

1. Obtain controlled unprivileged execution through the exposed UPnP/XML or
   service-console path; neither is established yet.
2. Validate a second-stage elevation on the exact package off-device,
   comparing setuid `sudo` 1.8.21 and an ARM32 GhostLock port.
3. Once root is established on the panel, copy all eMMC user and boot areas
   over the isolated Ethernet link and verify hashes before any firmware
   modification.

## Primary references

* [Linux stable 3.4.113 history with GUP race fix](https://kernel.googlesource.com/pub/scm/linux/kernel/git/jaegeuk/f2fs-stable/+log/8d1988f838a95e836342b505398d38b223181f17)
* [AF_PACKET capability requirement](https://man7.org/linux/man-pages/man7/packet.7.html)
* [CVE-2016-8655 capability analysis](https://access.redhat.com/security/cve/cve-2016-8655)
* [CVE-2017-1000112 researcher's analysis](https://xairy.io/articles/cve-2017-1000112)
* [glibc 2026 loader advisories](https://sourceware.org/pipermail/libc-announce/2026/000064.html)
* [glibc Looney Tunables introduction in 2.34](https://sourceware.org/pipermail/glibc-cvs/2024q1/084099.html)
* [glibc ISO-2022-CN-EXT advisory](https://sourceware.org/pipermail/libc-announce/2024/000040.html)
* [Qualys Baron Samedit advisory](https://blog.qualys.com/vulnerabilities-threat-research/2021/01/26/cve-2021-3156-heap-based-buffer-overflow-in-sudo-baron-samedit)
* [GhostLock discoverer's analysis](https://nebusec.ai/research/ionstack-part-2/)
* [Upstream Linux 3.4.97 rtmutex source](https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/linux-stable/+/refs/tags/v3.4.97/kernel/rtmutex.c)
* [Upstream Linux 3.4 futex source](https://raw.githubusercontent.com/torvalds/linux/v3.4/kernel/futex.c)
* [ARM32 GhostLock research and working port on another device](https://github.com/gitchw/ghostlock-cve-2026-43499/blob/main/README.md)
