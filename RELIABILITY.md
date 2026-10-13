# The Rural Update: coordinated publication

## Review and cutover

Read DEPLOYMENT_STATUS.md before merging. This overlay belongs in the existing
repository. It is not a standalone replacement for existing content or media.
The PR test job has read-only permissions and no API secrets. Opening a PR does
not publish an edition. Merging the reviewed change to main can start the first
real release and retires the three separate automatic writers at the same time.

Preserve the existing github-pages environment protections and branch rules.
Never expose credentials, force-push publication history, or broaden permissions
to get around a blocked action. Approval of an automated fact audit is not approval
of deployment and is not a guarantee of editorial accuracy.

## Ownership and authorization

Publish validated Rural Update is the sole automatic writer and Pages deployer.
Archive, speech, transcript, RSS and deployment are coordinated by that workflow.
The old workflows remain as manual, read-only retirement notices. The independent
watchdog can verify delivery, maintain a GitHub incident and request one recovery
through the same publisher; it cannot publish a competing edition.

OPENAI_API_KEY remains in repository Actions secrets. The research and evidence
review model defaults to gpt-5-mini and can be selected using RURAL_UPDATE_MODEL.
Speech uses gpt-4o-mini-tts with the cedar voice. Actual authorization, model access
and project billing must be verified in a live run. Bounded requests and retry
counts are not a monetary hard cap. Configure project billing controls in the
provider account, not in the website or source files.

## Intended operating times

All schedules use America/Chicago, including daylight-saving changes.

- 05:15: begin daily research and preparation.
- 06:00: target delivery time, not a guaranteed completion time.
- 06:10: verify public delivery and request at most one recovery for that edition.
- 06:30: verify again and maintain the incident if unresolved.

The separate ChatGPT delivery check is read-only. Do not activate a second ChatGPT
publication writer. GitHub-hosted schedules can be delayed and both repository
workflows share GitHub availability; the separate observer adds another signal.

## Release sequence

1. Resolve an explicit current Central edition date and read existing public state.
2. Research public sources with web retrieval and compile structured content.
3. Validate date, source references, required fields and 1700-2000 spoken words.
4. Run a separate automated evidence audit. Stop on an unsupported material claim.
5. Compile escaped content into a stable application template. Do not let daily
   research rewrite JavaScript, navigation, status colors or service-worker code.
6. Preserve unresolved issues, actual history and suggested actions. Do not infer
   real staff progress, completion or assignments from news sources.
7. Preserve a same-day dated archive and transcript as part of the release.
8. Produce speech using cached, content-hashed chunks and validate decoded audio.
9. Update RSS with a stable date GUID and the actual audio publication timestamp.
10. Build an allowlisted .site artifact and a file-size/SHA-256 release manifest.
11. Commit publication outputs together. Reject overlapping concurrent edits;
    retry safe disjoint updates a bounded number of times without force pushing.
12. Deploy the exact .site artifact, not a later checkout of a moving main branch.
13. Retrieve public files, check expected edition/revision/hashes, decode the MP3,
    validate range support and check episode/transcript references in RSS.

The RSS remains publicly accessible. Its directory-blocking metadata does not
provide authentication or make the feed private.

## Failure behavior

Invalid content stops before a production commit. Do not redate stale reporting.
If only audio fails, validated text and the transcript may publish with audio
unavailable. That is a partial release, not complete success. A recovery can use
approved text and successful cached speech chunks without starting another writer.
Unchanged completed releases can be re-deployed and verified without new research.

API retries are limited to transient HTTP errors. Per-date cached research attempt
counts, workflow timeouts and the watchdog recovery marker bound repeated work.
Cache loss can lose the local attempt ledger and chunk reuse. Those limits do not
substitute for provider billing controls or live operational monitoring.

One GitHub incident is maintained per edition. It reports the failing stage/run
without credentials. A successful issue creation does not establish that the user
received an email or device notification; receipt is part of live acceptance.

## Operator actions after approved cutover

Actions > Publish validated Rural Update > Run workflow, using main:

- publish: build or reuse today's approved edition, deploy and verify.
- recover: complete missing work through the same repeat-safe publisher.
- verify: inspect public delivery without paid generation or deployment.
- test-alert: create a clearly labeled test incident without publishing or paid API calls.

Leave edition_date blank for today's Central date. Automatic historical generation
is rejected. Historical corrections require an explicit reviewed revision.

To reproduce non-production checks:

```sh
python3 -m pip install -r requirements-publisher.txt
python3 -m unittest discover -s tests -p 'test_release*.py' -v
node --check web/release-runtime.js
node --check sw.js
node tests/test_release_sw.cjs
python3 -m compileall -q scripts tests
```

Synthetic fixtures run only in temporary directories and must never become a real
edition. Repository compatibility checks require the existing index, intelligence,
archive and branding files; they cannot be established from the overlay alone.

## Acceptance

Require successful repository CI, a complete authorized live research/speech run,
public delivery verification, actual iPhone and podcast-client checks, confirmed
receipt of a test notification, and seven scheduled mornings without manual repair.
Until those gates pass, distinguish code/test readiness from production reliability.
