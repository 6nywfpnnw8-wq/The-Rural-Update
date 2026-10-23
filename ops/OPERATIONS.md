# Daily Rural Update operations

## Status and approval boundary

The Render cron job `the-rural-update-morning-trigger` is active on the
repository's `main` branch. Its current configuration runs a read-only GitHub and
public-manifest preflight, then executes `ops/trigger_publisher.py --execute` when
`RURAL_UPDATE_EXECUTE=true`. Render logs on October 23, 2026 confirmed two accepted
GitHub workflow dispatches before the same-day limit guard stopped further requests.
Render remains the external clock; the GitHub Actions workflow is the only content
publisher. The service is configured in Render rather than a `render.yaml` file.

## One automatic morning clock

Render is the only automatic clock for publication. GitHub Actions accepts the
Render `workflow_dispatch` request and runs the single content publisher. Manual
workflow dispatch remains available for owner-directed recovery. A successful HTTP
dispatch means GitHub accepted the request; it does not mean the edition published.

The active Render cron job uses the repository's main branch, Python 3.11 or newer,
and no additional packages. Its current settings are:

- Build command: compile and test the trigger, then perform a read-only GitHub and public-manifest preflight.
- Start command: run `python3 ops/trigger_publisher.py --execute` when `RURAL_UPDATE_EXECUTE=true`; otherwise run read-only mode.
- Safe bridge test: `python3 ops/trigger_publisher.py --mode diagnose --execute`
- UTC cron: `5,35 10-13 * * *`

The UTC expression covers both Central daylight and standard time. The script only
acts between 05:00 inclusive and 07:00 exclusive America/Chicago. Thus the effective
checks are 05:05, 05:35, 06:05 and 06:35 Central; other UTC invocations exit without
network calls. The first check precedes the 06:00 target, later ones support bounded
recovery. This workflow has no GitHub schedule, so the two schedulers cannot launch
competing automatic editions.

Render documentation states UTC cron scheduling, one active run per cron service,
and a minimum monthly charge of $1 per cron job. Actual usage and account pricing
must be reviewed before activation: https://render.com/docs/cronjobs

## Credential boundary

Configure `GITHUB_ACTIONS_TOKEN` only as a secret in the external scheduler, never
in source code, logs, this document, a chat, or public Pages. Use a fine-grained
GitHub credential restricted to this repository with Actions read/write and
required metadata access. Content write, workflow-file write, administration and
OpenAI API access are not required for this external timer. Set an expiration and
an owner-controlled rotation reminder. A GitHub App installation token with the
same narrow repository permissions is an alternative for managed rotation.

The code sends authentication only to the fixed GitHub workflow API, rejects
redirects, reads the public release without credentials, and dispatches only
publish.yml on main. Preserve branch and environment approval rules. Never broaden
permissions in response to a blocked action without an independently justified,
owner-approved change.

GitHub workflow-dispatch permission reference:
https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

## Bounded decisions

Before starting work the external clock checks the public release manifest and
recent runs of the fixed publisher. A queued, active or approval-waiting publisher
prevents another request. A current complete manifest suppresses unnecessary work;
it is not treated as independent verification of the audio or sources. Two
observed same-day publish attempts stop automatic publishing. Read-only diagnostic
dispatches can validate the handoff without spending editorial attempts. The publisher retains
its own authoritative generation-attempt ledger and single-writer lock. Neither
this script nor the timer can reset those counters or override failed evidence.

Dispatch is rechecked against current run state. A request is made at most once
per invocation. If a POST times out, it is not blindly repeated. A later scheduled
check inspects actual run state again. A narrow cross-service race is still possible;
the existing publisher lock and repeat-safe release handling remain necessary.

On errors the script exits nonzero and emits metadata only. Configure and TEST the
external scheduler's failure notification channel. This program does not claim to
send email itself. Confirm real notification receipt on the user's device. A green
scheduler dashboard is not proof that anyone received an alert.

## Content and audio quality

Daily generation uses separate evidence-discovery, structured reporting and
narration requests, with hash-checked unapproved caches. Incomplete model responses
must retain safe status, stopping reason and usage metadata and must not become
approved drafts. Exact source retrieval and the independent evidence audit remain
mandatory. Verify proposed/final status, effective dates and primary sources; do
not fill a quiet day with fabricated news.

Narration must satisfy the current script length requirement, include every
intended segment and reach its complete ending. The publisher checks each speech
segment against independent audio-only transcription, checks decoded assembly and
checks the assembled ending. Preserve the script/audio hash binding. ASR checks
completeness, not perfect numerical pronunciation or clinical accuracy.

A text-only partial release is not a successful podcast release. Old reporting must
retain its actual date. Missing historical publication dates must not be fabricated.

## Storage and cost controls

Before accepting indefinite operation, measure actual published-site size, audio
bytes per episode, repository history growth and Actions-cache usage. Set a warning
at 70% of the applicable hosting quota and escalate by 85%; do not delete historical
files automatically. GitHub Pages documents a 1 GB published-site limit:
https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits

Daily MP3 retention should ultimately use an approved audio/object-storage service
with HTTPS, range support, stable URLs and tested RSS migration. Keep the date-based
episode GUIDs stable. A future hosting change requires explicit service/cost approval
and a validated migration. No audio has been moved or deleted by this change.

Track model usage by discovery, reporting, narration, audit, speech and transcription.
Bounded output tokens and retries reduce waste but are NOT a dollar-denominated hard
spending cap. Use provider project billing controls and review actual usage monthly.
Do not claim API credits are free or that a connected ChatGPT subscription covers them.

## Acceptance record

For seven successive mornings record scheduled-start time, trigger origin,
edition date, source-audit outcome, audio-completeness outcome, public verification
time, recovery count and any required human repair. Categorize results as on-time,
late, partial, manually recovered, missing or unverified. Only completed on-time
scheduled releases count toward the 06:00 unattended target.

Required fault tests: missed Render trigger, incomplete research response,
source rejection, bad narration ending, failed deployment, duplicate external
trigger, stale public cache, expired scheduler credential and notification failure.
A read-only status observer should remain separate from the publishing workflow.

## Tests and activation sequence

Run `python3 -m unittest discover -s tests -p 'test_release*.py' -v` and the existing
service-worker checks. Twenty-two specific external-clock tests use mock HTTP calls,
covering daylight-saving dates, duplicate suppression, dry-run, attempt bounds,
unknown POST outcomes and credential isolation. These do not replace verification of production authentication or the actual Render service.

For a safe end-to-end check, run the Render trigger with `--mode diagnose --execute`
during its Central morning window. Confirm GitHub records a `workflow_dispatch` run on
`main` with mode `diagnose`, and confirm the job does not access the provider or deploy
Pages. The normal scheduled command remains `--execute` with the default `publish` mode.
A dispatch acceptance is not publication proof. For a real edition, require successful
source/evidence checks, complete audio, Pages deployment, and exact public verification.
