# Privacy and sharing diagnostics

SpinDoctor works with local paths, game libraries and optional scraper accounts.
Secret redaction is not the same as anonymization. Review diagnostics before
posting them to a public issue or including them in a pull request.

## Sharing logs and reports

SpinDoctor redacts ScreenScraper passwords, developer passwords and TheGamesDB
API keys in its scraper log and handled scraper errors. Account names (`ssid`),
developer identifiers, game names, request URLs and filesystem paths can remain.
Do not assume every subprocess's output has the same redaction.

Before sharing:

1. Include the SpinDoctor version, OS, command and a short error excerpt.
2. Replace account identifiers, Windows usernames, hostnames, network-share names
   and private directory names with consistent placeholders.
3. Check URL queries, response bodies and encoded values for credentials.
4. Check screenshots for credential fields, account names, open folders and
   unrelated windows. Masked input fields do not sanitize the rest of the screen.
5. Share only the relevant excerpt, not the whole `.spindoctor` folder, library
   inventory or a full backup.

The same review applies to saved GUI output, audit CSVs, crash tracebacks and
RocketLauncher logs. Keep command structure and error text intact where possible
so the report can still be reproduced.

## Configuration, caches and backups

- `config.json` contains scraper credentials in its saved settings. Do not attach
  it unedited; share only the relevant keys with values replaced.
- Corrupt-config rescue copies and backup/migration snapshots can contain older
  credentials and absolute paths too.
- Undo manifests contain paths and may preserve database/configuration content.
  They are recovery files, not automatically anonymized diagnostic reports.
- Caches, favorites and the LEDBlinky library can reveal library contents and
  custom settings even when they contain no passwords.

Keep originals private and edit a **copy** for sharing. Do not delete recovery
records or the LEDBlinky library merely to sanitize a report. See
[Storage locations](spindoctor-files.md) for what each store contains.

If a credential was published, rotate or revoke it with its provider. Removing it
from the current file does not remove it from Git history, issue notifications,
previous downloads or other people's copies.

## Examples in this repository

Use placeholders such as `<hyperspin_dir>`, `<rocketlauncher_dir>`,
`%USERPROFILE%` and `<account>` in new examples. Runnable examples may use
illustrative paths such as `D:\Arcade` or `J:\Games`, but those are not required
locations or a description of a reader's machine.

The [example cabinet reference](cabinet-architecture-reference.md), controller
guide and OS-migration guide preserve hardware and integration examples. Treat
their mappings and paths as examples to adapt, not proof of anyone's current
installation. Do not add personal names, serial numbers, account IDs, private
hosts, real user profiles, unreviewed logs or panel photos to extend them.

CHANGELOG entries describe historical releases. Preserve that history unless a
specific disclosure needs removal; an example path or public project URL alone is
not a secret. Pattern scans help find common credential formats but cannot prove
that every identifying detail has been removed.
