# November 2 structured review incident

The retained response from run 41433972218 contains all 105 required fields.
Its global review_complete is true; 104 fields are true. Only
/sources/3/published_date is false, accompanied by one misleading_date finding
quoting the exact candidate value 2026-10-09. This violates the PR #141 instruction
that a completed examination with a blocking finding still reports completion.
The validator correctly rejects the response, but previously discarded actionable
field details from its diagnostic summary. It must never reinterpret false as true.

The provider completed with 8,620 output tokens against 10,000 permitted, including
6,464 reasoning tokens. No missing-field or truncation failure was reproduced.
The saved request digest is e8a3dea5223a3d17d91925171d8979befea4446c191d5d8fb0f3b9384147ef86.
The exported artifact retains the digest, response and original candidate, rather
than a full raw request. The request contract is reconstructed from the pinned code.

An independent download of the exact CMS URL matches the retained PDF SHA-256:
d94d56ad96583d541882ad68e410df1933020cd30d942cf17499dbd6998777b1.
It is a 2025 FAQ; its contents do not establish October 9, 2026 as an initial issue
date. An update date must not be substituted for initial publication. The reviewed
metadata correction changes only this source's published_date to null (unknown).
No prose, URL or citation identity is changed or approved by this correction.

The date-specific plan pins the candidate, original review and request hashes.
It uses only the unused final slot: two total audit requests, no new research,
reporting or generated corrections. All cited evidence is retrieved again and the
entire corrected candidate needs a complete independent review with live retrieval.
Incomplete, malformed, blocked or ambiguous final reviews remain consumed and stop.
No editorial override, podcast dependency or second publisher is introduced.

New diagnostics retain incomplete paths and validated findings without approving
publication. Future requests describe completion versus approval at the schema
field itself. November 2 request schemas remain byte-compatible for retained replay.
This wording change reduces ambiguity; it cannot guarantee future model compliance.

Regression tests reproduce the global-true/field-false date finding, retained
failure details, one-shot final review, no live retrieval, final rejection,
additional incomplete fields, changed candidates and budget tampering. The actual
retained 105-field response also reproduced the failure offline. A temporary
rehearsal of the real candidate used one simulated complete final review, zero real
API calls, and left the initial review and research ledger unchanged. Simulation
is not evidence of editorial approval or public delivery.

Sources: issue #143, PR #141, run 41433972218 artifact 13136326275.

## Validation and remaining execution

Local validation completed: 887 release tests passed with one existing skip;
JavaScript syntax and six service-worker checks passed. The latest diagnostic
artifact from run 41438021228 still has attempts=1 and only initial-reserved.json.

The tested correction is on branch fix/november-2-incomplete-metadata-review.
Automatic approval review rejected the branch push as an external export of
potentially sensitive diagnostic and metadata-review records. No PR, merge,
publication run or real editorial API call was completed in this investigation.
The committed records contain hashes, the implicated public CMS URL and date,
and the incident explanation; they do not include the retained full draft,
full provider response, credentials or original diagnostic archive.

Remaining execution after external-write approval:

1. Push this branch to the user's specified repository and open a PR. Require the
   repository's release-control CI checks to pass before merging.
2. Merge the correction and its pinned November 2 metadata plan.
3. Dispatch the existing Publish validated Rural Update workflow on main with
   mode=recover and edition_date=2026-11-02. If dispatch tooling is unavailable,
   update release-request.json through the existing main-branch push trigger on
   November 2. Do not create a second publishing workflow or call the model locally.
4. Confirm the publisher restores the November 2 resumable cache, preserves
   attempts=1, and submits only editorial-loop-v1/final. The original incomplete
   review must remain retained. If cache binding fails, stop rather than research anew.
5. Require a complete independent review of all 105 fields with live retrieval,
   no blocking findings, all normal release validations, Pages deployment, and
   exact public inventory hashes. Report the actual outcome and run URL.
6. If the final review fails or is ambiguous, retain it and stop. This plan
   authorizes no additional review, research, reporting or correction generation.

The edition is recoverable from retained material in offline rehearsal, but real
editorial acceptance and public delivery remain unverified. This change must not
be described as proof that future daily publication cannot fail.

The research entry point also refuses new research if this pinned recovery plan
exists but its retained candidate is missing or structured review is disabled.
