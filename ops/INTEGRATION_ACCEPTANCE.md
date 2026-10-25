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

All stages must pass for integration acceptance. A failure stops progression and
retains evidence; later stages are not represented as successful. An automatic
evidence audit is not human editorial approval. A passing report does not prove
public HTTP/range delivery, on-time scheduling, or future unattended reliability.
The initial cohort does not establish broad normal-day and quiet-day coverage.

`acceptance.html`, `acceptance.json`, the offline test log, development request
ledger and screened checkpoints are preserved as Actions artifacts. Failed and
ambiguous submissions remain spent within this development budget. Another test
plan or a production publication request requires its own explicit scope.

References:
- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments
