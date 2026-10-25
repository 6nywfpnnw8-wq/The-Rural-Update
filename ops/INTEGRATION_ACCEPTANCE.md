# Nonpublishing integration acceptance

The integration workflow tests the actual publisher and provider in a separate
workspace. Its output is a development acceptance report, never a public edition
or a production recovery authorization. The Render clock and the single publisher
remain unchanged.

## Inputs and isolation

`integration-request.json` binds the October 25 cohort to the retained discovery,
eight-source catalog, original context identity and original attempt-ledger hashes.
The workflow restores the production cache for read-only seed copying. It never
saves to a production cache key or copies a production attempt/recovery/approval
marker into the development cache.

Development state is under `.integration-state`, saved only with the
`rural-integration-v1-<request-id>-...` cache prefix. The compiler runs against its
isolated workspace using the same `research_payload`, staged generation, source
collector, editorial audit, narration, speech validation and site builder used by
production. A changed seed/context stops before discovery; discovery and source
selection submissions are prohibited by the transport guard.

Revision 3 continues the exact retained development state. Its request binds both
the previous plan hash and original development-ledger bytes. A checked migration
preserves that ledger as a separate artifact and retains every spent request.
Lost or changed state blocks the continuation instead of creating a fresh budget.

The job has `contents: read`, no Pages or repository-write permission, and no
persisted Git credential. It references the existing credential environment with
`deployment: false`. No publish command, commit/push step or incident writer runs.
The existing shared concurrency group prevents overlap with the publisher.

## Execution and request ceilings

The user authorized creating and running this bounded development test. A change
to `integration-request.json` on trusted main starts it once. Manual dispatch
defaults to a non-generating seed check; explicitly select `live=true` for a live
development run. This is not a scheduled workflow.

The persistent development ledger caps actual HTTP submissions, including retries:

| Endpoint | Maximum submissions |
|---|---:|
| Structured responses, combined | 32 |
| Speech | 64 |
| Transcription | 80 |

Within the response ceiling, reporting and full narration each allow at most two
submissions; sectioned narration allows at most 20. The existing production audit,
correction and audio-specific limits still apply. Per-stage output-token ceilings
match the production requests. Tool use, speech input and transcription byte sizes
are also bounded. These are request/token ceilings, not dollar-denominated billing
limits.

The coverage correction adds at most one `reporting_plan` HTTP submission with
6,000 output tokens inside the existing combined ceiling of 32. The previous
reporting submission remains spent, leaving at most one reporting submission.
Retries count as submissions. A failed or ambiguous planning submission cannot
silently obtain a fresh planning allowance.

Revision 4 binds the exact two-request ledger left by that first live planning
test. It adds at most one further planning submission to validate the corrected
passage selector, for a lifetime planning ceiling of two inside the same combined
32-response ceiling. Both earlier ledger versions and every spent row are retained.
The reporting ceiling remains two. A lost, changed or ambiguous ledger cannot
obtain a fresh budget.

Each submission is reserved before transport. Known HTTP errors remain counted;
an ambiguous submission cannot be automatically repeated. The ledger and retained
responses survive failure and resume. An absent ledger after retained provider
work does not create a fresh budget. No script resets a production ledger.

## Evidence and pass criteria

The workflow retains a screened visible completion or audio response before the
compiler can reject it. It excludes request prompts, hidden reasoning and raw API
envelopes from response snapshots. Source working material and generated reporting
remain explicitly unapproved for publication.

The acceptance report distinguishes passed, failed and untested stages:

1. Offline controls and seed integrity.
2. Real provider reporting and narration contracts.
3. An intentional stop before narration, followed by reporting-cache reuse with
   no repeated reporting submission.
4. Date, reference, content and full narration checks.
5. Exact source retrieval and the independent automated evidence audit.
6. Speech completeness, assembled ending, script/audio hashes and decoded duration.
7. Local site, archive, manifest, transcript and RSS integrity.
8. An exact completed rebuild with zero additional provider requests.
9. Rejection of a deliberately corrupted local artifact.
10. Byte-identical production public files and attempt/recovery checkpoints.

Before drafting new reporting, the compiler retrieves every selected source with
the existing public HTTPS, redirect, MIME, byte-size and text-size checks. A
separate coverage plan must identify five distinct story angles and four distinct
signal angles. Each selected reference needs a verbatim passage found in that
source's actual text. The publisher splits normalized source text into numbered,
bounded passages. The model selects an integer passage index or null for each
source; code inserts the exact text. Free-text quotes, nonexistent indexes and
boolean values cannot substitute for passage selections. Stories retain their one-to-five source requirement; signals
retain their two-to-four distinct-source requirement. Unsupported slots can be
left empty with `insufficient_evidence`, which blocks drafting. Completed negative
plans are retained and do not cause automatic provider retries.

The compiler supplies planned story/signal IDs, titles, policy/change labels and
citation sets to the finished report. The prose generation schema cannot replace
those fields. A matching passage establishes presence, not semantic entailment or
editorial approval. The final candidate's exact retrieval and independent evidence
audit still run normally. Existing completed reporting checkpoints continue through
their original validators and audit rather than spending requests to re-plan them.

The first coverage-provider test (run 40232788745, commit e54d78e) retrieved all
eight retained pages but rejected a single-source RHC signal and five free-text
anchors that rearranged or changed source text. Evidence coverage v2 replaces
that copying contract with code-bound numbered passages. Revision 4 continues
the isolated test with the bound, previously spent ledger described above.

All stages must pass for integration acceptance. A failure stops progression and
retains evidence; later stages are not represented as successful. An automatic
evidence audit is not human editorial approval. A passing report does not prove
public HTTP/range delivery, on-time scheduling, or future unattended reliability.
The initial cohort does not establish broad normal-day and quiet-day coverage.

The offline runner writes structured unittest results tied to the actual source
commit. Successful suites with explicitly skipped tests are reported with their
skip count; console-summary wording is not used as an acceptance parser. Failed
suites, unexpected successes and mismatched commit identities still block the run.

`acceptance.html`, `acceptance.json`, the offline test log, development request
ledger and screened checkpoints are preserved as Actions artifacts. Failed and
ambiguous submissions remain spent within this development budget. Another test
plan or a production publication request requires its own explicit scope.

Retained reporting failures can be inspected without another provider request:

```bash
python3 ops/integration_acceptance.py --replay-artifact /path/to/extracted-artifact
```

This reads the preserved acceptance report, response snapshot, source checkpoint
and development ledger. It verifies the response hash, lists all structural
rejections, checks that the ledger is unchanged, and writes an enriched local
report. The original live-test commit and outcome stay recorded; the diagnostic
replay commit is recorded separately. The command cannot be combined with
`--live` and grants no publication approval. A successful replay command means
diagnostics completed, not that the rejected report passed acceptance.

The retained October 25 provider response is a test-only regression fixture.
It verifies rejection of an uncited fifth story and two signals selecting only
one source each. All three citation failures must be corrected with relevant
supporting material before later stages can be exercised. Citation counts alone
do not establish evidence support; exact retrieval and independent audit remain
required.

References:
- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments
