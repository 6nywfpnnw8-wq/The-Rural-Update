# November 3 source selection and PDF coverage incident

## Exact failures and origin

The November 3 edition failed before a coverage plan, report or editorial review
was generated. Artifact 13226912877 from run 41628763038 retains both selection
completions and the exhausted research ledger. Read-only inspection run
41654114083 additionally confirmed intact discovery and nine-source checkpoints,
no reporting checkpoint, no editorial reservations and no approved candidate.

The two diagnostics describe different attempts, rather than two simultaneous
schema defects in the same response:

| Attempt and run | Exact rejection | Origin |
| --- | --- | --- |
| 1: 41624634129 | `/sources`, `maxItems`: 13 selected records, maximum 12 | Source-selection generation returned thirteen non-null choices. The nullable map used by generation did not structurally enforce the compiled array's count. Local schema validation correctly rejected it. |
| 2: 41628763038 | `/sources/3`, `src-02dd9737ced55c32`, source retrieval `ValueError` | The exact Federal Register PDF has 118 pages; the reader capped PDFs at 100 pages. A valid selected source exceeded the reader's page-count bound. |

The first completion's SHA-256 is
`b53c31d772f4dfeae91b81d90e97afe10c10b1021e5c0c0c08abf974300e0f37`.
Its thirteen selected IDs are preserved verbatim in
`tests/fixtures/source-coverage-2026-11-03.json`. No one source was individually
invalid under that count error, so dropping an arbitrary thirteenth source would
not be a justified repair.

The second completion's SHA-256 is
`e8cc0ea1e7319ce4319e7c14d2a15ceae0721b51f7548e3e2aa76aa78fefe1b0`.
It passed source-catalog validation with these exact records:

| Index | Source ID | Source | Retained retrieval result |
| --- | --- | --- | --- |
| 0 | src-db7e2228ed4f8b9c | Oklahoma RHTP Quick Reference Guide PDF | HTTP 200, extracted |
| 1 | src-90945e8746da757b | Oklahoma RHTP program page | HTTP 200, extracted |
| 2 | src-dd9d4f7688485958 | Oklahoma RHTP funding page | HTTP 200, extracted |
| 3 | src-02dd9737ced55c32 | Federal Register CMS-2452-P NPRM PDF | Rejected at page-count limit |
| 4 | src-3236e8cccb97f0d6 | CMS MLN MM14468 PDF | HTTP 200, extracted |
| 5 | src-9315ed0d2cc3ed6e | CMS Transmittal R13776OTN page | HTTP 200, extracted |
| 6 | src-299e421cf61e682c | CMS provider-tax proposed-rule fact sheet | HTTP 200, extracted |
| 7 | src-4f1464923f786235 | CMS rural transformation awards announcement | HTTP 200, extracted |
| 8 | src-cc7888b1e0b22d4c | CMS GENEROUS participants announcement | HTTP 200, extracted |

The failed exact URL is
<https://public-inspection.federalregister.gov/2026-14897.pdf?1784664910=>.
An independent download contains 690,029 bytes with SHA-256
`0efe61097260582b2b4624fa7c826f08c63949373da179805c3fff6bf68a1b2a`.
With only the page cap changed to 160, the pinned pypdf 6.21.4 reader extracts
all 118 readable pages, 267,214 characters, and text SHA-256
`d40b0f06c34f42dba500daffc60546d8dc36489c4496875ecff677368dc88a84`.
The original cap reproduces the exact `ValueError` before extraction. This
establishes a deterministic reader failure, rather than an HTTP outage or a
missing model-generated source record. The original diagnostic discarded the
specific exception text, so this attribution is independently reproduced from
the pinned code and exact public document, not inferred from `ValueError` alone.

## Targeted changes

New source-selection requests have five required source slots and seven optional
slots. IDs come from the observed-source enum and the publisher supplies URLs.
A response cannot structurally select thirteen sources. Duplicate or invented IDs,
extra fields and invalid metadata remain rejected. No source is silently trimmed,
and historical map completions and selected checkpoints retain their contracts.

PDF extraction is bounded at 160 pages and still requires readable text on every
page. The 2 MiB response limit, page and total stream limits, 300,000-character
source limit, 450,000-character combined limit, HTTPS/domain/DNS/redirect checks,
full-source review and live supersession checks remain enforced. No PDF is
truncated or substituted. Future page-limit failures retain allowlisted counts;
array-count schema failures retain actual count and required limit.

The normal exhausted two-attempt ledger correctly stopped automatic generation.
It did not provide a way to resume a successfully retained source selection after
a deterministic reader correction. The reviewed date-specific continuation in
`coverage-resume/2026-11-03.json` pins discovery, sources, failure report, ledger,
request identity and the independently downloaded PDF. It permits only one
coverage-plan request and one reporting request, with no tools in either request.
It adds no discovery, source-selection, narration or podcast request and leaves
`attempts=2` byte-for-byte unchanged. Each permitted request is reserved before
submission; malformed, rejected, incomplete or ambiguous results remain consumed.
Missing or changed checkpoints, a changed PDF, changed context or disabled
structured review stop before additional model calls. Insufficient evidence still
prevents reporting. A complete report still needs the existing independent
editorial loop, exact-source retrieval, release validation and public hash checks.

## Verification and execution

Local validation: 901 tests ran, with 900 passing and one pre-existing skip. This includes
fourteen incident regressions, both actual retained source responses, exact
independently downloaded incident PDF bytes, all-page extraction, count bounds,
zero new research/source-selection calls during simulated continuation, unchanged
ledgers, exhausted/ambiguous requests, insufficient coverage, cache loss, changed
PDF and disabled editorial review. JavaScript syntax and six service-worker
checks passed. Simulated reporting does not establish factual approval.

Execution uses the existing `publish.yml` workflow on main, the same edition
date and the existing single-publisher concurrency group. Updating
`release-request.json` can invoke it if workflow dispatch is unavailable. The
continuation must restore the inspected November 3 cache, retrieve all nine
sources, match the reviewed PDF and pass the new coverage plan before reporting.
Independent editorial review and exact public-delivery verification are still
required. This document records the tested correction; it does not assert that
November 3 was published or that future publication cannot fail.

Sources: [issue #145](https://github.com/6nywfpnnw8-wq/The-Rural-Update/issues/145),
[failed retry](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41628763038),
[first attempt](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41624634129),
[read-only inspection](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41654114083).

## Actual recovery outcome: not published

[PR #146](https://github.com/6nywfpnnw8-wq/The-Rural-Update/pull/146) was merged
after both reliability CI and live exact-source checks passed. Recovery ran
through the existing publisher in
[run 41655791262](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41655791262).
Its preserved artifact is `release-reports-41655791262-1`, ID 13239796655,
expiring November 17, 2026. All nine exact sources were retrieved, including
all 118 pages of the original Federal Register PDF with the reviewed byte and
text hashes. The reader correction is therefore verified in the production
workflow, as well as offline. The new selection format was verified by regression
and CI; recovery reused the existing nine-source selection rather than generating
another selection.

The one permitted coverage-plan request completed and returned
`status=insufficient_evidence`. Its retained visible-response SHA-256 is
`98c6f29cc07cc14ea2bcc17720d2a7485a6badc7f1c4f87208423f4e9ed50465`.
Validation correctly stopped on these remaining findings:

| Missing item | Exact evidence gap |
| --- | --- |
| `/stories/story_5` | The proposed payer-administrative-change story has no supporting payer primary-source record in the retained set. Discovery notes explicitly acknowledged that its payer examples came from legacy context and were not supported by approved-domain retrieval. |
| `/signals/signal_4` | The proposed GENEROUS implementation signal has only the CMS participant announcement. No second relevant supporting source was retained in the selected set; the signal requires two to four. The single-source announcement may support a story, but that does not satisfy the signal requirement. |

This is a substantive research/selection shortfall exposed after the deterministic
reader failure was fixed. It is not another source-schema error or HTTP failure.
The discovery/selection process had not established enough supported themes to
meet the fixed five-story/four-signal publication contract. A different supported
theme could be considered only after verifying its exact relevant passages; this
investigation has not established that such a replacement exists.

No reporting, editorial audit, generated correction, podcast or deployment was
attempted in this recovery. The research ledger remains `attempts=2`; the
coverage-plan reservation remains consumed; the reporting request is unused.
Diagnostics made zero additional model calls. The normal provider readiness
probe also ran; it did not generate replacement briefing research. The public
release record continues to identify the November 2 app edition. Issue #145
remains open. The publishing system must not be described as fully repaired.

Remaining requirements are concrete: obtain or verify an approved primary-source
record for a genuinely supported fifth development and a second relevant source
for the fourth signal, or substantiate different non-repetitive replacement
topics from retained material. Then a separately reviewed, bounded coverage-plan
continuation must bind the new evidence and the consumed reservation. The current
authorization does not permit a second plan request, new discovery, new source
selection or a research-limit reset. After a complete valid plan, the unused
reporting stage and the normal independent editorial review, release validation,
Pages deployment and exact public hash verification remain necessary. No silent
retry or validation bypass has been installed to force publication.

The regression now replays this exact negative response as well: both missing
slots remain blocking, no report is generated, and replay makes no model call.

## Authorized evidence completion

The user's subsequent instruction to proceed authorizes a bounded completion of
the remaining evidence work. The new `app-evidence-completion-v2` policy in
`app-evidence-recovery/2026-11-03.json` adds three independently retrieved sources
that were already present in the original observed retrieval events:

| Source | ID | Supported use |
| --- | --- | --- |
| [Oklahoma RHTP Programs](https://oklahoma.gov/rhtp/rhtp-programs.html) | src-1dfc766a5c4dc1e2 | State rural residency, recruitment and CareerTech LPN pathways |
| [CMS summit readout](https://www.cms.gov/newsroom/press-releases/readout-cms-convenes-first-rural-health-transformation-summit-advance-state-led-innovation) | src-7b662f962f90b96c | Federal workforce training, residency, recruitment and retention priorities; published March 19, 2026 |
| [Oklahoma Year One microgrant NOFO](https://oklahoma.gov/content/dam/ok/en/health/health2/aem-documents/health-promotion/rhtp/microgrants/Microgrants%20NOFO_VFinal.pdf) | src-bc7e6e2b0702e1be | Reimbursement administration, spending restrictions and the notice's November 30 invoice date |

The unsupported payer story is excluded. A distinct continuing workforce-pipeline
story and signal can instead draw on relevant state and federal evidence. Grant
administration and reimbursement timing remain a separate executive issue.
The microgrant application and expenditure dates have already passed. The policy
forbids describing an open application window or approved late spending, assigning
unverified awards or enrollment, treating old announcements as new, and transferring
workforce-program eligibility into microgrants that prohibit staffing expenses.
Unknown initial-publication dates remain null.

The reviewed set has twelve sources and 386,764 characters, below the unchanged
twelve-source selection cap and 450,000-character combined-evidence limit. Five
stories and four two-source-minimum signals remain required. No evidence-count or
approval requirement has been reduced. New byte, text and media-type hashes are
pinned in the date-specific policy and verified again during CI and execution.

The old plan, source/discovery checkpoints, consumed reservation and attempts=2
ledger are preserved. The completion authorizes one additional plan request, for
two total, and one reporting request overall, in a separate resumable workspace.
It authorizes no discovery, source-selection model request, narration, podcast,
counter reset or approval override. Missing or changed predecessor records, source
changes, excess source additions, disabled structured review, changed context or
ambiguous submissions remain blocking. The old reader-only authorization is not
reopened or combined with the new allowance.

Local validation: 913 tests ran with one existing skip, and JavaScript syntax and
six service-worker checks passed. Twelve additional regressions cover source,
context and budget binding, mixed HTML/PDF evidence, preservation of prior work,
ambiguous submissions and continued independent-review enforcement. A rehearsal
using the actual retained checkpoints and exact downloaded source text produced
the required five/four/twelve structure with two simulated downstream requests,
zero real model calls, unchanged original records and no editorial approval.
Real coverage acceptance, independent review and public delivery must still be
verified through the existing publisher.

Live CI retained two known HTML byte variants for each of the state-programs and
CMS-summit pages. In both cases, the complete extracted source text has the same
reviewed SHA-256. The policy accepts only those explicitly reviewed byte hashes
(maximum two per HTML source), plus the same exact full-text hash and media type.
The PDF requires its one exact byte hash. Unknown byte variants, changed text,
changed media or additional wildcard/duplicate hashes remain rejected. No model
request was spent while these live source differences were investigated.

## Reviewed reporting assignment after the repeated plan failure

[Run 41663506084](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41663506084)
retrieved and bound the added evidence, then consumed the second permitted plan
request. Its completed response repeated the unsupported payer story and GENEROUS
signal assignments rather than using the replacement workforce topic. It also
selected eight references for story 3 (maximum five) and seven for signal 1
(maximum four), including an unrelated telehealth reference for grant coverage.
The actual rejected output is retained in artifact 13243042230 and replayed in
`tests/fixtures/coverage-completion-rejection-2026-11-03.json`. Validation stayed
blocking. No reporting or independent editorial review had started.

`reporting-plan-review/2026-11-03.json` now records an explicit reporting assignment
using fixed passage indices from the twelve exact retained sources. It contains
five distinct story assignments and four signal assignments, with two sources per
signal. It separates grant invoice administration from workforce pathways and
recurring operating-cost planning, corrects the GENEROUS application-versus-
execution distinction, and excludes the unsupported payer claim. This is a
reviewed assignment for drafting, not approval of final prose or publication.

The reporting-only continuation pins the failed run, consumed reservations,
parent policy and context, all source checkpoints, the rejected plan and the
reviewed compiled plan. It copies the valid assignment into a separate workspace
without overwriting either rejected model plan. The normal coverage validator
still checks every slot, distinct reference count and exact passage. Only the
one unused reporting request is permitted; discovery, source selection and a
third coverage-plan request are prohibited. Research attempts remain two.
Independent full-field review with live supersession retrieval and normal public
delivery verification remain mandatory. Ambiguous reporting remains consumed.

The actual parent cache also passed a reporting-only offline rehearsal: one
simulated report request, no planning or real API calls, unchanged prior records,
and the required five/four/twelve structure. Regression coverage includes the
actual repeated-plan failure, invalid reviewed assignments, changed predecessor
records, used reporting slots, budget expansion, cache replay, and an incomplete
independent review that still prevents approval. Real public delivery remains
unverified until the existing publisher completes it.

## Completed report reference repair

[Run 41666553636](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41666553636)
completed the one reporting request. The response used 3,401 output tokens against
16,000 permitted and was not incomplete. Its exact visible-text SHA-256 is
`66e3ecaaa3c7282d85b4538afd0d43788a4038dca2a67faa69472931738b505a`.
The only structural defect is `/actions/2/source_ids`: six references against a
maximum of five. The completed report is retained in artifact 13244069468.

The reviewed correction in `reporting-response-review/2026-11-03.json` reduces
only that action's citation set to the two directly relevant sources: the CMS
summit passage on durable financing and the microgrant notice's restrictions on
staffing, maintenance and subscription costs. It preserves the action's wording,
every other prose field, all source records and the original raw response. The
normalized candidate SHA-256 is
`ee78b99c1594ef080d38cbcd8241830694d25285af7c81db98fe475830028230`.

The replay requires the exact completed API metadata, consumed reporting request,
assignment and source checkpoints, raw response and sole recorded schema error.
It can only remove the reviewed references, not add sources or alter prose. The
unchanged report validator must pass after the reduction. This performs zero
discovery, source-selection, planning or reporting requests and leaves attempts=2.
The report then enters ordinary fresh source retrieval and independent full-field
editorial review. Neither review slot had been used before this repair.

The actual retained report replayed successfully offline with unchanged original
records and no model calls. Eight regressions cover raw-response completion,
source/prose binding, no budget expansion, replay, unsafe paths, and independent
review that still blocks an incomplete audit. No publication approval is granted
by the citation repair.


## Verified publication and public delivery

The November 3, 2026 app-only edition, revision 1, was published successfully by
[run 41669673274](https://github.com/6nywfpnnw8-wq/The-Rural-Update/actions/runs/41669673274).
The initial independent full-field review completed with live retrieval, zero
blocking findings, zero advisory findings and no generated editorial correction.
All twelve exact source records were retrieved successfully. The approved
candidate hash is `ee78b99c1594ef080d38cbcd8241830694d25285af7c81db98fe475830028230`,
matching the reviewed reference-correction candidate. No further discovery,
source-selection, planning or reporting request was made during this successful
run. The original research ledger remains `attempts=2`.

Pages deployment and exact public-inventory verification passed. The delivery
report records all ten files verified at 10:03:35 AM Central on November 3, 2026.
A separate fresh public GET confirmed that both `release.json` and the homepage
identify November 3, revision 1, in app mode, and that the homepage bytes match the
release-manifest hash. [Issue #145](https://github.com/6nywfpnnw8-wq/The-Rural-Update/issues/145)
was closed automatically after successful public verification.

Preserved proof: `release-reports-41669673274-1`, artifact ID 13246889802, expires
November 17, 2026. The [published edition](https://6nywfpnnw8-wq.github.io/The-Rural-Update/archive/2026-11-03.html)
contains five developments, four signals and twelve sources. Podcast production
remained excluded. The 933-test suite and release-control checks passed; the
successful production review and public hashes establish this edition's recovery,
not a guarantee that every future research result will satisfy the evidence gates.
