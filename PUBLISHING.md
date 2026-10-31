# The Rural Update publication

Effective October 31, 2026, new editions update the app only. Podcast narration,
speech, transcription, transcripts, and RSS generation are retired. Historical
editions and their existing media remain available in the archive.

The versioned format boundary is in `scripts/release_publication.py`. App editions
have no `podcast` field. Their release manifest records `publication_mode: app`
and has no audio status or new media inventory.

## Daily publication

1. Render remains the sole automatic publication clock. It dispatches the existing
   GitHub publisher and respects the current run and attempt limits.
2. The publisher checks research and web-search capability, selects sources,
   retrieves their exact evidence, and validates coverage before reporting.
3. It compiles the app briefing and runs the independent source evidence review.
   An incomplete or rejected review blocks publication. A bounded field correction
   still needs a fresh complete audit.
4. It saves the app, intelligence and signals data, archive, and release inventory
   atomically, then deploys the validated snapshot to GitHub Pages.
5. Public verification checks the exact edition and every inventoried file's size
   and hash. Successful app delivery does not depend on a podcast or transcript.

The two-attempt research limit, source verification, editorial controls, retained
cache, and single-publisher lock remain enforced. A format change cannot approve
failed research, reset a ledger, or make an older edition current. Repeat delivery
of an intact completed app release reuses its committed files without generation.

## Operations

- Daily publisher: `.github/workflows/publish.yml`.
- Delivery watchdog: `.github/workflows/publication-watchdog.yml`.
- Offline app acceptance: `.github/workflows/integration-acceptance.yml`.
- Source failures: inspect the retained `validation-*.json`, source evidence,
  stage responses, and structured review records before requesting recovery.
- Legacy media code remains for compatibility with historical release records;
  the active daily path does not generate or validate new media.
