# The Rural Update publishing workflow

The repository now separates **content generation** from **publication mechanics**.

## Daily publication sequence

1. Prepare the new `index.html` edition.
2. Keep the visible edition date in the header. For maximum reliability, future generated editions should also include:

   ```html
   <meta name="edition-date" content="YYYY-MM-DD">
   ```

3. Commit the new `index.html` to `main`.
4. GitHub Pages publishes the updated root document from `main`.
5. The `Archive previous Rural Update edition` workflow runs automatically because `index.html` changed.
6. The workflow reads the prior `index.html` from Git history, preserves it as `archive/YYYY-MM-DD.html`, updates `archive/catalog.json`, and commits those archive changes back to `main`.
7. The Archive tab reads `archive/catalog.json`, so only real, available editions are shown.

## Safeguards

- Existing archive snapshots are treated as immutable. The workflow fails rather than overwrite an existing dated archive with different content.
- Updating an edition without changing its date does not create a duplicate archive entry.
- A workflow-generated archive commit does not trigger another archive run because the workflow is scoped to changes in `index.html`.
- No external API key is required for archiving or GitHub Pages publication.

## Current limitation

This workflow does **not generate the daily intelligence brief**. It automates version preservation, catalog maintenance, and publication after a new `index.html` is supplied. Content generation can be connected separately through ChatGPT or another approved generation process.
