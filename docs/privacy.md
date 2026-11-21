# Privacy and sharing diagnostics

Redaction is not anonymization. Scraper logs mask passwords/API keys in handled
paths, but account identifiers, URLs, game names and filesystem paths may remain.
Subprocess output can have different protections.

Before posting an issue or sharing a report:

1. Include version, OS, command and only the relevant error excerpt.
2. Replace usernames, account IDs, private hosts/shares and paths consistently.
3. Inspect URL queries, encoded values and response bodies for secrets.
4. Review screenshots, including unrelated windows; launch tests can capture the
   whole monitor. Masked credential fields do not sanitize the rest of the image.

`config.json`, rescue copies and settings backups can contain credentials.
Manifests, logs, caches and library lists can reveal private paths/content.
Review a **copy**; do not destroy recovery records or the preserved LEDBlinky
library to sanitize a report. [Storage map](spindoctor-files.md).

If a credential was published, revoke/rotate it. Deleting the latest copy does
not remove Git history or downloaded copies.

Repository examples must use synthetic data and placeholder paths, not real
profiles/accounts/logs. The [cabinet reference](cabinet-architecture-reference.md)
preserves example wiring, not anyone's current installation. Historical
CHANGELOG/review entries remain dated records.
