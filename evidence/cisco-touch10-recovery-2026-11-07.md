# Cisco Touch 10 recovery procedure and local implications

Checked 2026-11-07. This is documentation review and read-only verification;
no reset, pairing, upgrade, or boot-state change was performed.

## Cisco's CE9.9 guidance

The [Cisco CE9.9 administrator guide](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/ce99/sx10-administrator-guide-ce99.pdf)
distinguishes two Touch 10 hardware versions:

| Version | Identifier | Cisco's panel reset sequence |
| --- | --- | --- |
| Cisco Touch 10, launched late 2017 | Logo on front, fewer rear connectors; reset and maintenance Micro-USB under a small rear cover | Open rear cover; hold reset until front mute button blinks, approximately 5 seconds; release. |
| Cisco TelePresence Touch 10, first version | No front logo, additional rear connectors | Hold Mute until it blinks red and green, approximately 10 seconds; press Volume down twice. |

The panel resets and restarts. Cisco says the reset is irreversible, removes
pairing information, and leaves the video endpoint itself unchanged. A LAN
connected panel must then be paired again. In the same guide, Cisco says that
if the panel needs a software upgrade during pairing, it automatically
downloads and installs it **from the video endpoint**, then restarts. The
guide recommends doing a panel factory reset in contact with Cisco support.

The CE9.9 guide's **Maintenance > System Recovery** swap of a previously used
software image is a procedure for the **video conferencing endpoint**, not a
standalone Touch 10 bootloader or eMMC recovery command. Cisco's separate
[IX5000 troubleshooting procedure](https://www.cisco.com/c/en/us/support/docs/collaboration-endpoints/telepresence-ix5000/200587-IX5000-Touch-10-troubleshooting.pdf)
lists log collection, a PoE power cycle, factory reset, and reconnecting to a
compatible MX/SX endpoint to retrieve a factory package as a last resort.
That article concerns IX software, so its button sequence and software
behavior must not be applied uncritically to this CE9.9.0 panel.

These public Cisco sources do not provide a user procedure for reflashing the
Touch 10 over its maintenance Micro-USB port or repairing eMMC/U-Boot when
the panel cannot boot far enough to pair. This is a statement about the
checked sources, not proof that no Cisco service procedure exists.

## What a reset means on this unit

The Touch 10's installed `/apps/bin/factoryreset` script was read over root
SSH and its SHA-256 matched the recovered CE9.9.0 package:
`8b14d2285869d42e505d240699a118ceec0d6d3c96b1cd26b183404f387cb2e4`.
Its current code:

- saves only selected configuration files, then recreates or invalidates
  writable filesystems and keys;
- calls `upgradebootsw` from the active installation;
- runs product-specific hooks; and
- normally deletes the inactive image directory unless an explicit
  `KEEP_OTHER_IMAGE` setting is present.

The persistent root SSH setup uses `/config` and `/user` files, which are not
on the script's default preservation list. A panel factory reset would
therefore likely remove that access. It could also remove the inactive
software slot and rewrite boot software. This assessment comes from the
installed script; the reset itself has **not** been tested here. The full
pre-reset eMMC and EEPROM backup remains on the PC.

For the current recovery investigation, pairing with the original codec can
provide an authentic Touch 10 package while the panel's normal firmware is
running. It is not a proven rescue path for a U-Boot or early-boot failure,
because the panel must reach its setup and upgrade client first.
