# Room Navigator CE26.5 public advisory check, 2026-11-07

The image analyzed in the local reports is the April 2026 cloud package
`bifrost.pkg`, revision `ce-26.5.0.50-44-gc49cadf5f59`. The version and URL
are recorded in [the package comparison](room-navigator-ce26.5-updater-comparison-2026-11-07.md).

[Cisco's RoomOS 26 release notes](https://roomos.cisco.com/doc/WhatsNew/ReleaseNotesRoomOS_26)
list a later standalone Room Navigator package,
`s53350ce26_7_3_3.pkg`, and identify the 26.7.3.3 release as September
2026. This establishes that newer firmware exists; it does not show the
contents of that package. The April cloud image is older and is not a
substitute for a 26.7 binary comparison.

The [Cisco download catalog](https://software.cisco.com/download/home/286333883/type/280886992/release/RoomOS%2026.7.4.3)
also lists `s53350ce26_7_4_3.pkg`, dated 26 October 2026, for standalone
table and wall variants. Its visible Download action requires a Cisco login
and an associated valid service contract. The
[access check](room-navigator-newer-package-access-2026-11-07.md) records
that result; no post-fix package was obtained.

[Cisco's July 2026 RoomOS hardening advisory](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-hardening-roomos-AqNMbEq)
groups multiple internally discovered issues by broad CWE class. It lists
26.5.2.2 as the first fixed on-premises RoomOS 26 release and RoomOS June
2026 (26.7.1.7) as the first fixed cloud release for those grouped issues.
The April `26.5.0.50` image precedes both. The advisory does not describe
the `peripheral-swsync.service` symlink-following `chown`, the
`updatesw` cleanup behavior, or the exact underlying bugs. Therefore its
CVE-2026-20150 (access control) and CVE-2026-20153 (input validation/path
control) **cannot be assigned to our findings** from the public text alone.

[Cisco's April 2023 arbitrary-file-write advisory](https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/cisco-sa-roomos-file-write-rHKwegKf)
includes CVE-2023-20091 for a local symbolic-link overwrite requiring a
remote-support account. Its published description does not identify the
CE26.5 `chown`/`fswatcher` chain or the old CE9.9.0 `swsync`/`curl` chain.
Similarity of weakness class is insufficient to treat it as the same issue.

[Cisco's security vulnerability policy](https://www.cisco.com/site/ca/en/products/product-security-vulnerability-policy.html)
asks researchers to send suspected vulnerabilities to PSIRT at
`psirt@cisco.com`, with a detailed description, evidence, and relevant logs.
A private report should include the exact package revision, offline proof,
runtime prerequisites, and the question whether the July 2026 hardening
release already fixed these paths. No disclosure has been sent.
