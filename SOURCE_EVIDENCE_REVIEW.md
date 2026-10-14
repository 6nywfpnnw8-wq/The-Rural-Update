# Exact evidence retrieval correction, October 14, 2026

## Verified failure

Production run 38579961526 passed its automated evidence audit but stopped at the
source-provenance gate. Source URLs supplied by an operator were not represented
as retrieval evidence, which was correct. The API audit's retrieval metadata did
not include every reference. A read-only HTTP preflight (38581254633) then retrieved
two exact CMS pages but received HTTP 403 for the HHS guidance listing.

The HHS listing identifies Federal Register document 2026-14897, CMS-2452-P. Its
linked original GPO HTML is the reviewed replacement:
https://www.govinfo.gov/content/pkg/FR-2026-07-23/html/2026-14897.htm

## Correction

The publisher now fetches readable content from every cited source before the paid
audit, records actual response/text hashes, and gives that content to the auditor
as untrusted reference data. HTTP success is not editorial approval. The auditor
must still search for superseding information and reject unsupported claims.
Missing or blocked source content stops the process before an audit call. HTML,
XHTML and plain text are supported; PDF references are not supported by this reader.

A hash-bound October 14 source-only correction replaces one metadata record. No
briefing, narration, deadline, action or signal claim is changed. It requires the
specific retained provenance-rejected snapshot and a complete new evidence audit.
The current deployment request authorizes at most one additional correction audit;
research generation counters and earlier audit reservations are not reset. A failed
audit cannot silently repeat through this correction. Source retrieval alone cannot
promote a candidate to an approved edition.

The public site artifact excludes cached source bodies and diagnostic candidates.
Only response metadata and the candidate-bound audit record enter report artifacts.
Never add confidential sources to this public-source workflow or cache.

## Tests and live gates

Locally, 142 Python tests passed without skips, including actual repository template
compatibility and 16 new source-retrieval/recovery tests. Six service-worker checks,
Python compilation and JavaScript syntax checks also passed. Paid API calls and
network content in these tests were simulated.

The PR additionally retrieves all 11 exact references in GitHub using read-only
HTTPS, without model calls or production writes. That preflight must pass before
merge. It proves retrieval, not factual correctness or public release delivery.

A temporary read-only UTC clock diagnostic is scheduled for October 14 at 16:05
and 16:15 UTC. It uses no checkout, credentials, API, content writes or deployment.
It is intended to determine whether GitHub emits a schedule event at all. Success
would not independently prove the 05:15 Central publishing schedule or 06:00
availability. Remove the probe after its diagnostic window.

Merging starts the existing coordinated publisher. Only its source audit, speech,
release commit, Pages deployment and public verifier can establish the completed
release. iPhone playback and notification receipt remain device-level checks.
