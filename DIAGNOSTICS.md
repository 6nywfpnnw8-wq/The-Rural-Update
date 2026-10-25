# Publication diagnostics

## October 13 incident

The second live run produced a 1,959-word narration but stopped at `Placeholder
text`. That version did not retain the rejected candidate or identify a field.
It is not possible to establish from its logs whether the marker was unfinished
content, a URL, or ordinary prose. This release does not claim to recover that
missing evidence or change the old validator's decision.

## New behavior

The publisher retains an initial public-source candidate before narration work and
captures the candidate passed to content/provenance/release-record validation.
These are diagnostic snapshots only. They cannot be used as approved editions and
are not read by the normal approved-cache path.

A rejected candidate now produces a report containing the processing stage,
failed validation rule, exact schema field path, measured narration length and,
for placeholder matches, the matched marker. For example, a **synthetic test**
returns `/podcast/developments/1 (matched "tbd")`. That is not a finding from the
lost October 13 draft.

Schema failures report their field and failed keyword without logging the rejected
instance. Alerts can include a safe summary from the current run; they will not
reuse another run's cached failure. All original content checks remain in force.
The original placeholder regex in release_core.py is unchanged.

## Storage and privacy

Full diagnostic snapshots remain under `.release-cache/YYYY-MM-DD/candidates/`.
Known credential formats and currently configured API/GitHub secret values are
redacted before snapshot storage. Do not use this capability for confidential,
patient, contracting, or other non-public source material. Redaction is a limited
safeguard, not a guarantee that arbitrary sensitive material could be detected.
GitHub Actions caches are not confidential storage.

Normal report artifacts contain field paths, fixed marker terms, counts and
checksums, plus the date-scoped attempt ledger and screened visible source-selection
completions under `stage-responses/`. Those completions contain public-source metadata
only and are retained before parsing or validation, so rejected source choices can
be replayed. They exclude prompts, reasoning and raw API envelopes. A redacted
completion is explicitly marked and cannot establish an unchanged original.
The report upload uses explicit patterns and excludes `candidates/` and `approved.json`. Full candidates
are not committed to main or copied into the Pages artifact. Existing artifact
retention is 14 days; cache retention is controlled by GitHub and is not guaranteed.

Reference: https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching

## Read-only diagnostic mode

Actions > Publish validated Rural Update > Run workflow > mode `diagnose`.
Use main and select the edition date to inspect. This mode restores existing cached
work and writes a diagnostic summary only. It does not receive OPENAI_API_KEY,
call the research/speech APIs, change the attempt counter, generate an edition,
commit files, deploy Pages, or claim public delivery.

Equivalent local command, after the cache has been restored:

```sh
python3 scripts/release_pipeline.py --date YYYY-MM-DD --diagnose-cached
```

The command refuses `--commit`. A successful diagnostic command means only that
the inspection completed. `publication_authorized` and `publication_verified`
remain false. A missing candidate is reported as `not-retained`, not reconstructed.

## Spending and publication gates

The two-attempt daily research limit, two narration-revision limit, evidence audit,
source-provenance checks, 1,700-2,000 word range, single-writer lock and public
verification requirements are unchanged. This update does not reset the exhausted
October 13 ledger or force an unverified edition through publication.

Merging this code can trigger the normal single publisher. If the October 13 cache
is restored, that run must stop at the existing two-attempt limit without making
another API request. A subsequent scheduled date receives its ordinary date-specific
budget, not an expanded one. Live completion remains subject to every gate.
