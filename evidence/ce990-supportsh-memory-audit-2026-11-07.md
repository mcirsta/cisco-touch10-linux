# CE9.9.0 `supportsh` memory audit (2026-11-07)

Target: the matching package's `apps.img/bin/supportsh`, copied to
`firmware/codec-ce9.9.0/analysis/touch10-ce990-supportsh` (SHA-256
`7f2fa80b1080afb4576c1a1d798aba084c9e1187ba8bd9adbf7660c45a3edb6c`).
This is offline IDA review and QEMU execution of the matching package
binary, not a byte-for-byte dump from this unit. No test input in this
audit was sent to the physical panel.

## Reachable input and memory bounds

* `main` (`0x1a24`) reads at most 1,023 bytes plus NUL with
  `fgets(line, 1024)`. `tt_rstrip` and `get_first_word` use unsigned-byte
  ctype indices. The first token goes into a 1,024-byte BSS buffer at
  `0x1605c`. `process_files` copies another token into a separate
  1,024-byte buffer at `0x1645c`; its NUL write is relative to that second
  buffer, despite confusing decompiler output.
* `show` and `head` use `fgets(..., 1024)` into 1,024-byte stack buffers.
  `tail` uses ten 1,024-byte slots and indexes them modulo ten.
  `print_file_contents` reads at most 1,024 bytes into a 1,024-byte stack
  buffer. File names come from six static aliases.
* `tailf` duplicates the bounded argument line, tokenizes it with
  `strtok`, and caps its path and descriptor arrays at 16 entries. The six
  static aliases each map to one path.
* `handle_os_command` (`0x269c`) filters bytes, then uses
  `__snprintf_chk` with a 1,024-byte destination and size limit. It does
  not use an unbounded format operation. The OS-command smoke test ran with
  `PATH=/nonexistent` to exercise the wrapper without launching host tools.
* `bootlogo` (`0x2ea4`) supplies only `on` or `off` to the write path. The
  linked EEPROM code reads the fixed 32-byte `bootlogo` partition into a
  matching allocation and checks for NUL before using string routines. Its
  getter receives a 64-byte destination limit. `eeprom_ascii_remove`
  (`0x4270`) uses `strcpy` on overlapping ranges, which is undefined by C,
  but the destination precedes the source within the same bounded EEPROM
  buffer. This review did not establish an out-of-bounds write from that
  overlap.

## Reproduced defects

1. `process_files` (`0x2100`) computes each next-token position from the
   **original** argument pointer plus the length of the most recently
   parsed token. After `show main kern`, both tokens have length four, so
   it repeatedly processes `kern`. `head` and `tail` share this handler.
   QEMU produced 3,697,479 bytes in one second before `timeout` stopped
   it. This is an infinite-loop/CPU and output denial of service, not a
   demonstrated memory overwrite. The SIGINT handler merely sets a flag;
   `process_files` does not check it. See
   `evidence/supportsh-multifile-loop-2026-11-07.json`.
2. On an early `open` failure, `handle_tailf` (`0x2a0c`) closes all
   requested descriptor slots even though later slots were never
   initialized. With `tailf main kern` and the first log absent, QEMU's
   syscall trace shows `close(-1)` followed by `close(0)`, closing the
   console's stdin. This is an uninitialized stack read used as a file
   descriptor; it can disrupt the support session, but does not grant
   access to another process's descriptors or root. See
   `evidence/supportsh-tailf-fd-trace-2026-11-07.log`.

## Exploitability of the two defects

The parser error is visible in ARM instructions at `0x21d8`–`0x21dc`:
`strlen` measures the latest token in `R10`, then `ADD R10,R6,R0` starts
the next scan from `R6` (the original argument pointer) plus that length.
`R6` is never advanced as a cursor. A complete 7-by-7 test of the six file
aliases plus `all` found 15 two-token combinations that timed out. This
includes equal-length pairs such as `main kern` and length-plus-one pairs
such as `console messages`. The loop repeatedly reopens fixed log paths;
it does not allocate a new buffer or move its write pointer on each
iteration. Sending SIGINT to the QEMU process left it running after 300 ms,
as expected from the signal handler. See
`evidence/supportsh-alias-pairs-2026-11-07.json` and
`evidence/supportsh-loop-sigint-2026-11-07.json`.

The descriptor bug is visible at `0x2b74` (store an attempted `open`
result), `0x2b78` (branch on failure), and `0x2b84`–`0x2b94` (close loop).
The loop closes `R4` requested paths, although only the attempted prefix
of the 16-slot descriptor array was assigned. With an absent first alias,
the second slot remains uninitialized; QEMU closed fd 0. With 16 repeated
absent aliases it also closed fd 1. More than 16 aliases are capped, so
this is an in-bounds read of uninitialized stack words, followed by
process-local `close()` calls; it is not an out-of-bounds read/write. Six
different prior log-content fills and six prior `ip` argument lengths did
not change the observed fd 0 closure. I found no way to select an arbitrary
descriptor or turn this into code execution. See
`evidence/supportsh-tailf-uninit-depth-2026-11-07.json`,
`evidence/supportsh-tailf-stack-reuse-2026-11-07.json`, and
`evidence/supportsh-tailf-prior-command-2026-11-07.json`.
Closing fd 0 has a second effect in `main`: `fgets(stdin)` fails but
`feof(stdin)` remains false, so the outer prompt loop retries. Without a
pre-buffered `quit` command, QEMU emitted 221,184 bytes of repeated `$ `
prompts in 0.2 seconds, until the host stopped it. This is a second route
to a sustained console denial of service. See
`evidence/supportsh-tailf-closed-stdin-loop-2026-11-07.json`.
Earlier live serial evidence shows that the `main` alias was absent on
this panel (`evidence/service-diagnostic-snapshot-2026-11-06.log`), so an
early-open failure is a realistic case. I did not run the disruptive
`tailf` sequence on the panel.

The straightforward fixes would be to advance a real argument cursor in
`process_files`, and to close only initialized nonnegative descriptors in
`handle_tailf`. These are root-cause descriptions; the firmware binary was
not patched.

## Dynamic checks

* 160 bounded and randomized file-command inputs: no process crashes;
  expected timeouts for the multi-file loop and argument-free `tailf`.
  `evidence/supportsh-memory-smoke-2026-11-07.json`.
* 111 OS-command wrapper inputs, with host command execution disabled:
  no nonzero exits or timeouts.
  `evidence/supportsh-os-command-smoke-2026-11-07.json`.
* 21 successful `show`, `head`, and `tail` reads under a private
  `bubblewrap` mount using 0-byte through 1-MiB test logs: no process
  crashes. `evidence/supportsh-file-reader-smoke-2026-11-07.json`.
* 11 non-writing `bootlogo` argument cases: no process crashes.
  `evidence/supportsh-bootlogo-smoke-2026-11-07.json`.
* 48 `bootlogo on` executions against a private, fake 32-byte EEPROM
  partition with valid, malformed, and randomized contents: no process
  crashes. These wrote only the temporary fake EEPROM file inside the
  `bubblewrap` mount. `evidence/supportsh-eeprom-smoke-2026-11-07.json`.

The tests cover a small corpus and QEMU is not the panel's kernel or EEPROM.
The console parser defects are real in the exact userspace binary, but this
audit found no input-driven out-of-bounds write or control-flow hijack.
`supportsh` runs as the unprivileged `support` user, so these defects do not
provide the local code execution needed for GhostLock or an eMMC backup.
