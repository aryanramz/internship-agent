# Employer/ATS registry

The registry extends the existing local `boards` source JSON. It does not replace
SQLite or change posting IDs, application states or audit history. It requires no
Google credentials, MCP connection, paid service or database migration.

## Local CLI

```powershell
# Fictional example: register disabled, with no network or database access.
internship-agent add-source https://jobs.lever.co/example --company "Example Employer" --disabled --careers-url https://example.com/careers
internship-agent list-sources
internship-agent suggest-sources --limit 25
# Only an explicit --apply registers suggested boards. It still does not fetch them.
internship-agent suggest-sources --limit 25 --apply
```

Replace the fictional URL/name only with an authorized public employer board.
`add-source` and `list-sources` do not initialize/open SQLite. Suggestions read the
existing local ledger; preview changes no configuration and explicit registration
does not retrieve jobs. A later explicit `discover` fetches enabled configured
sources using fixed provider endpoints, not the metadata URLs.

Commands retain `--sources config/sources.json`; other local files may be selected
explicitly. Default private source files, common employer-registry filenames and
atomic-write temporary files are ignored and rejected by repository hygiene.
Keep operational registries under ignored `config/sources.json` or `data/`, never
in public fixtures. [The source example](../config/sources.example.json) uses
fictional disabled employer entries; its original public aggregate feeds retain
their existing enabled defaults.

## Version 1 fields

The top-level object retains `boards` and existing extension fields. Optional
`registry_version` is `1`; other versions are rejected rather than guessed.

| Field | Meaning and validation |
|---|---|
| `provider`, `token`, `company` | Existing reader contract; `company` remains the display label. Required provider-specific `host`, `site`, `domain`, feed/import fields retain their meaning. |
| `enabled` | Boolean, default true. Strings such as `"false"` are errors. Disabled boards are never fetched. |
| `employer_id` | Stable 24-character hex identity, separate from job IDs. On first normalization it derives from the board namespace, not the employer name. Explicitly persisted IDs survive display-name changes. |
| `employer_name` | NFKC-normalized, whitespace-collapsed display name matching `company`; no control characters. Names alone never merge employers. |
| `board_url` | Canonical public hosted board URL matching provider/token/host/site/domain; job URLs can be detected for registration but are stored as the board root. |
| `careers_url` | Public HTTPS employer careers URL, default board URL. Metadata only; never fetched by registration/discovery. No credentials, IP literals, intranet hosts, nonstandard ports, query or fragment. |
| `provenance` | `{method, url}` with manual/suggested/imported method and a public HTTPS source reference. Suggestions record the detected board root. |
| `validation` | `{status, checked_at, evidence, http_status?}`. Status unverified/passed/failed/blocked. Recorded results need a timezone-aware ISO timestamp and nonempty short sanitized evidence; HTTP status is an optional integer. |

Employer metadata applies to company ATS boards. Existing aggregator, RSS and
local import configurations remain supported without pretending that a feed is
an employer. Unknown existing extension fields are retained when explicitly
writing the configuration. A configuration is bounded to 4 MB on read and write.

Validation fields are operator-maintained evidence notes, not a cryptographic
attestation or permission to bypass the reader. Record the actual dated endpoint,
result and limitations locally after qualification; do not paste raw responses,
contact details, credentials or personal application information into the note.
Discovery does not automatically promote registry validation to passed. Issue #10
maintains separate SQLite [scan health/evidence](DISCOVERY_LIFECYCLE.md), without
rewriting private source configuration.

## Identity, duplicates and compatibility

- Old valid `{"boards": [...]}` files load without a migration or write. Defaults
  appear in the inspected view only. Registration explicitly persists version 1
  and normalized metadata while retaining existing reader settings/extensions.
- Board identity includes provider/token plus domain, host and case-sensitive
  site where relevant. Feed URLs and import paths retain their case-sensitive
  namespaces. Duplicate source entries are reported, not fetched twice.
- Re-registering the same board is a byte-preserving no-op, even if the caller
  provides a different display name; existing ownership/validation/enabled
  metadata is not silently overwritten. Change configuration explicitly to edit it.
- Different boards with the same employer name receive distinct default IDs.
  To link an additional **verified** board, pass the existing `--employer-id` and
  matching normalized employer name. Conflicting names for one ID are rejected.
  To rename an employer, update company/employer_name together across its entries
  and retain employer_id. Never infer shared ownership from a name alone.
- Registration validates the entire batch/existing registry before one atomic
  replacement. Duplicate registration writes nothing; a failed replacement leaves
  the original intact and cleans its temporary file. POSIX temporary files use
  private permissions; Windows relies on the local account's filesystem ACLs.
- This is single-writer local configuration. Simultaneous editors can still race;
  there is no registry-file lock. SQLite discovery leases/checkpoints do not lock
  this JSON file. No unattended scheduler is installed.

See [live qualification](LIVE_ATS_VALIDATION.md), [source coverage](SOURCE_MATRIX.md)
and the [master roadmap](ROADMAP.md).
