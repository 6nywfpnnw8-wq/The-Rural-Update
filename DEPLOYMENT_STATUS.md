# Reliability release review: October 13, 2026

## Scope

This change stages the October 11 reliability bundle for controlled review on
`reliability-pipeline-v1`, based on production commit
`f394e1946ee1ee1eee646dbd2baeffd766e006e5`.

It is an overlay for the existing repository, not a replacement website. Existing
briefs, intelligence source files, archives, icons, audio, transcripts and RSS are
preserved. No generated edition is included in this pull request.

## Validation status before pull-request CI

- Original bundle checksums matched the supplied manifest.
- All 31 original Python fault-injection tests passed again locally on October 13.
- All six Node service-worker isolation checks passed again locally.
- Python compilation, JavaScript syntax and six workflow YAML parse checks passed.
- Four additional read-only repository compatibility tests were added. These
  require the real repository and must pass in the pull-request CI run.
- Local GitHub clone was unavailable due to container DNS. Connector reads were
  successful. Local tests are not represented as live API or deployment tests.

## Do not confuse staging with cutover

Opening the PR does not publish or change main. The PR's test workflow uses a
read-only token and requests no API secret. The publishing and recovery workflows
only run on trusted main, not the PR branch.

Merging this PR is a production cutover: the three legacy workflows lose automatic
write/deploy triggers and the unified publisher's main push trigger can initiate a
real release. Do not merge merely because the branch is mergeable.

Before merging, review successful CI, production model authorization and billing,
OPENAI_API_KEY availability in Actions, the existing github-pages environment,
and the first-run plan. Never expose a key or weaken repository protections.
The default research model is gpt-5-mini; the speech model is gpt-4o-mini-tts with
cedar voice. Actual availability must be confirmed in the authorized environment.

The prior platform block does not establish a GitHub permissions deficiency.
Do not broaden permissions or force a write to overcome a safety refusal.

## Live acceptance after an approved cutover

1. Observe the first real publisher run and its content/evidence gates.
2. Verify the public edition/revision, checksums, archive, MP3, transcript and RSS.
3. Confirm actual iPhone playback and podcast-client refresh.
4. Use test-alert and confirm notification receipt, not just issue creation.
5. Observe seven consecutive scheduled mornings without manual repair.

Until all live gates pass, label this release staged/tested, not live-validated.
