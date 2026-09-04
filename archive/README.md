# Archive architecture

The `archive/` directory contains immutable published snapshots of The Rural Update.

## Naming convention

Use one HTML file per published edition:

`YYYY-MM-DD.html`

Example:

`2026-08-31.html`

## Catalog

`catalog.json` is the machine-readable index of editions that actually exist in this repository. Future publishing automation should update the catalog only after the corresponding archive file has been committed successfully.

## Publishing sequence

1. Copy the current published dashboard to `archive/YYYY-MM-DD.html`.
2. Generate or update the new root `index.html`.
3. Add the archived edition to `archive/catalog.json`.
4. Commit the changes together when possible.
5. Allow GitHub Pages to publish from `main`.

Do not add archive links for files that have not been committed. This prevents broken historical links from being presented as available editions.
