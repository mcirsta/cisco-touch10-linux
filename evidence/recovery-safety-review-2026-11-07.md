# Recovery safety review, 2026-11-07

Scope at the time of writing: exact CE9.9.0 Touch 10 artifacts, saved device
backup, TI OMAP4460 documentation, and read-only live checks. A later
owner-authorized console and `bootz` test succeeded; see
[the live proof](uboot-bootz-live-proof-2026-11-07.md).

## Corrected ROM map

The [TI OMAP4460 memory map](https://www.ti.com/jp/lit/pdf/swpu316) places
the 48 KiB on-chip Boot ROM at physical `0x40030000`–`0x4003bfff` and marks
`0x40000000`–`0x4002ffff` reserved. Our earlier Linux helper targeted
`0x40028000`; its fault at `0x4002f000` is in that reserved region. Its zero
prefix and external abort cannot be used to infer ROM contents, protection,
or read accessibility. A later 16-byte `/dev/mem` `read()` at the corrected
ROM base returned `Bad address` and no bytes; the mapped ROM range and a
U-Boot `md` read remain untested. The historical helper sources are labeled
as wrong-address probes.

## Existing recovery evidence

- The full eMMC user area, both eMMC boot areas, and board EEPROM are backed
  up in `backups/touch10-2026-11-07/`. The main image hash was rechecked on
  the PC as `a89710444605d06dd5995b793274bc4d4974a86c6656fea04430dd3c7aadc9ac`.
  The eMMC RPMB is not in this backup, and a filesystem image captured while
  Linux was running is not an atomic snapshot.
- The current 256 KiB partition 8 environment still hashes to
  `bd527afd42a26a7b983775d05c33c1860c879ef61f38da0c0329f92610839eca`
  on read-only SSH retrieval, matching the saved image. Its `XXXX\n` prefix
  has an invalid U-Boot CRC, so the observed boot uses compiled defaults.
- The exact MLO in partition 1 and both U-Boot copies in partitions 6 and 7
  match the recovered CE9.9.0 package. The environment address used by the
  exact U-Boot is `0x08b60000`, exactly the start of GPT partition 8. Its
  `0x40000`-byte save span ends at partition 8's end; it does not overlap
  partition 9 in the static code path.
- The offline environment candidate has a valid CRC and preserves all 25
  compiled defaults. It has **never been flashed**. Its intended `bootcmd`
  stores `run normalboot` before reaching the console, with the factory
  command in `normalboot`. The exact post-save bytes cannot be predicted
  because U-Boot exports its live variable table.
- The compiled default `upgradenetwork` command itself contains nested
  `if ... then ... else ... fi` blocks. This supports the candidate's Hush
  grammar choice, but does not prove its execution on this panel.

## Outcomes and remaining failure cases

| Case | Evidence now | Remaining risk |
| --- | --- | --- |
| Candidate CRC rejected | U-Boot falls back to compiled defaults and boots normally. | This is inferred from the existing bad-CRC boot path, not a test of this candidate. |
| `setenv` or `saveenv` reports failure | The command attempts `run normalboot` in the same boot. | A partially completed `saveenv` or an unexpected Hush parse failure has not been exercised. |
| Save succeeds and serial console works | **Observed:** `CONSOLE_READY`, `TOUCH10>`, valid saved CRC, and interactive commands. | A second ordinary reboot has not yet directly observed the saved normal boot path. |
| Save succeeds but console I/O is unavailable | Not observed; console I/O worked in the live test. | This would matter only in a different failure state. |
| Initial command is misparsed before the save | Not observed; the candidate parsed and saved correctly. | The general failure branch is not proven for future variants. |
| Correct ROM address is read from Linux or U-Boot | A 16-byte `/dev/mem` `read()` at the correct base returned `Bad address`; U-Boot `md` was not run on ROM. | HS-device mapped access and abort behavior are unknown. |

The existing root SSH and raw backup substantially improve recoverability,
but SSH depends on Linux booting. They do not provide a known way to recover
from an unusable U-Boot environment if the self-restoring command fails.
The later live test validated the candidate's successful parser and save
branch. Its failure branches remain untested. A future ROM read should start
with a separately reviewed, bounded access to the **correct** address; it
must not reuse the historical helper or assume that a full 48 KiB read is
safe.
