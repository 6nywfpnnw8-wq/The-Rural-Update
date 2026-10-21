# Editorial review and audio comparison repair

This release enables a structured editorial review in the existing single publisher.
No schedule, credential, public app layout, or source list is replaced.

## Exact failures reproduced

The October 21 retained draft passed its structure checks but received a mixed
list of factual concerns and advisory observations. The new reviewer must name
an existing field, quote its exact text, identify existing source IDs, and classify
the finding. Unsupported assertions remain blocking even when embedded in advice.
A completed review with advisory findings only can pass. A model review remains an
automated quality gate, not a guarantee of factual accuracy or human approval.

The two October 20 rejected speech samples both independently transcribed the
expected closing sentence. The source said `passthrough`; transcription said
`pass-through`. Tokenization treated these as different final words and rejected
the speech. Normalization now recognizes this specific orthographic equivalence
and straight/curly apostrophes. Acceptance thresholds are unchanged. Tests retain
rejection of missing final words, half-compounds, and mid-sentence cutoffs.

## Bounds and evidence

For one same-date draft: one structured review, at most one correction request,
and one fresh full-source review. Requests are reserved before submission and
results are checksum-bound to the request. Ambiguous request failures are not
resubmitted automatically. The same day cannot start a new loop for another draft.
All real source retrieval, web search, schema, provenance and audio checks remain.
A failed corrected draft stays unpublished. Source URLs, IDs and edition date
cannot be rewritten by the correction request. Earlier generation counters and
failed verdicts are preserved. A retained rejected draft can enter this bounded
review without another research-generation attempt.

Production enables the feature only in the publishing step with
`RURAL_UPDATE_STRUCTURED_REVIEW=true`. Existing tests cover the legacy path;
the new integration suite explicitly enables and exercises the production path.
No API key is used in pull-request tests.

## Validation before production

Local tests: 452 Python tests and six service-worker checks passed. The actual
October 21 retained candidate passed the checkpoint-loader identity checks. Local
API/audit behavior was simulated. GitHub CI and a full live publication still
must establish deployment success. Seven on-time unattended mornings and actual
notification receipt remain operational acceptance criteria.

The temporary read-only inspection workflow is removed from this review branch.
Unpublished cache contents are not copied into the public website. Historical
October 20 audio is not automatically republished or used as today's episode.
