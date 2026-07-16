# Account-scoped Google Takeout saved-place intake

**Status:** complete — local and protected remote verified
**Owner:** PlaceIntel saved-place domain
**Scope:** local-first and protected-private Takeout ingestion; no Google
mutation, third-party data upload, or external enrichment.

## Problem

The original saved-place importer treats every Google Takeout export as the same
`source_product`. Two accounts with a list sharing the same name would therefore
collapse into one collection. A prior real import is already present without an
account scope and must be labelled without creating duplicate collections or
memberships.

## Contract

- `saved-import PATH --source-label LABEL` uses an opaque, operator-supplied
  source label; it must not require or print an email address.
- The effective collection source identity is
  `<existing-source-product>:<normalized-label>` and becomes part of the
  existing collection identity. Logical saved items remain shared by exact
  Maps/content identity, while list memberships stay scoped.
- Import receipts record the normalized source label. JSON output exposes the
  label but never archive paths, titles, notes, comments, or account addresses.
- `--adopt-unlabeled` is only valid with `--source-label`. It promotes an
  existing unlabelled collection when the incoming source file digest proves it
  is the same export; otherwise it fails atomically rather than guessing.
- Re-importing the same archive under the same label is idempotent. The same
  export under a different label creates separate collections/memberships but
  reuses logical saved items where identities match.

## Delivery and verification

1. Add deterministic unit and CLI contract tests for scoped identities,
   idempotency, safe adoption, and invalid adoption flags.
2. Add the receipt migration and scoped import implementation.
3. Update the agent CLI, architecture, operations, and saved-places PRD only
   where the user-visible contract changes.
4. Back up the local DB, adopt the original archive under its opaque account
   label, import the second archive under its own opaque label, then repeat both
   imports and verify zero new records on each repeat.
5. Run the focused saved-place and backup suites, the full Python suite, CLI
   doctor, and source-controlled diff checks. Raw archives remain outside git.

## Completion receipt

- The prior real archive was adopted into its opaque source scope with no new
  collections, items, or memberships.
- A second real archive used localized filenames. Its review GeoJSON was
  excluded; its strict saved-place GeoJSON signature produced one collection,
  47 memberships, and 38 new logical items.
- Repeating either archive under its own source label produced zero new logical
  records. The aggregate private corpus is 89 collections, 4,075 items, and
  4,144 memberships.
- The private deployment completed from the private repository before remote
  intake. The host database was backed up first; archives were staged only in a
  permission-restricted memory directory, imported with opaque source labels,
  and removed automatically. The replay created zero records for both sources.
- The final protected inventory matched the aggregate corpus; SQLite integrity,
  cheap doctor, and deployment smoke all passed at version 0.4.73.
