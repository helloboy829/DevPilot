# Verified human QA summaries

## Product flow and formula

In **Projects & datasets**, select a project, explicitly load review runs, select
an effectiveness run, then click **Load / refresh verified summary**. Nothing is
loaded merely by rendering the summary panel. Case operations invalidate the
visible summary; changing run/project or leaving the page discards it. A failed
refresh clears the previous number, with no automatic retry or unverified fallback.

The denominator is the frozen plan's **entire sample count**, not the current
page, successful requests or reviewed subset. Effectiveness requires exactly one
planned attempt per frozen sample; repeated performance requests are rejected.

`human_pass_rate = latest human PASS count / frozen plan sample count`

PASS, FAIL, UNCERTAIN and UNREVIEWED are mutually exclusive latest-decision counts.
Revision history never creates extra votes. Unreviewed, uncertain, technical
failure and undispatched cases remain in the denominator. No automatic judge,
semantic tolerance decision, threshold or project PASS is introduced here.

The number is a **read-time preview**. `review_complete` only means collection
finished normally, every sample has verified output evidence and all latest human
decisions are PASS/FAIL. It does not mean all samples passed. Incomplete collection,
missing evidence, uncertain or unreviewed cases yield explicit blockers and
`provisional` status. Even a complete review returns `acceptance: not_approved`.
The present API does not create an immutable archived report or approve a project.

## Integrity and privacy

`app.evaluation.qa_summary.SummaryRepository` batches the run's bounded metadata,
shared frozen source, outputs and **latest** encrypted reviews. The frozen dataset
and gold-bound hash are verified once, not once per case. Each ordinal/sample,
technical observation, output envelope and latest review envelope is then checked
outside the event loop and outside DB locks, reusing evidence case verification.
Latest revision count must equal its revision number, so gaps cannot silently
change the counted vote. Full historical note verification remains the explicit
per-case history operation; this summary authenticates the current decision only.

Before returning, a DB run-row lock serializes a full snapshot reread against
normal observation/review writers. Any concurrent change rejects the read; only a
matching snapshot gets a transactional `human_summary_opened` audit event. There
is no lock held across crypto, network or model I/O. A missing key or corrupt
source/evidence is an error, never a reason to fall back to plaintext counts.

Response fields include counts, technical completeness, exact fraction, plan hash,
readiness and an evidence/revision-bound `summary_hash`. It returns no Q, A, gold,
notes, reviewer identifiers, ciphertext or case list. Repeated reads with no
source change have the same summary hash; a new human revision changes it. The
hash identifies a preview, not persisted report evidence or a substitute for
future immutable report binding.

## API and permissions

`GET /api/evaluation/projects/{project_id}/review-runs/{run_id}/summary`

Requires authenticated project ownership, both evaluation read and review
permissions, and a human caller (internal agents cannot read it). Responses are
private/no-store. It sends no target/model requests and never grants execution
permission. Existing case-list counts remain metadata-only; they are not silently
upgraded to verified summaries.

No schema migration, new operator setting, model key, target allowlist or Docker
volume change is required by this slice. Code App head remains `eval_0007`; local
confirmed deployment is still `eval_0006` while Docker API diagnostics time out.
The previously pushed execution commit
`0e56c3b60216350c3f598414b8b4eb02d842494a` passed all six triggered workflows;
that is not evidence for this newer summary change until its own SHA is checked.

## Validation gates and next steps

Tests cover fixed denominators, latest revisions, uncertainty, completeness versus
approval, corrupt output/decision/gold, missing ordinals/revision gaps, owner scope,
read/review permissions, internal-agent rejection, unavailable keys, concurrent
revision changes and off-loop single shared-source verification. DOM and browser
coverage checks explicit loading, refresh failure, stale-response discard and
mobile width. Local validation for this summary change: 281 related backend
regressions passed; frontend unit tests passed in 138 files (1,066 tests, zero
skipped); frontend check and the 95-page production build passed; production-build
browser tests passed (191 business cases plus 2 authentication recovery cases,
one worker, zero retries, synthetic APIs). Ruff check and formatting passed across
1,182 backend files. These overlapping subsets are not a full Windows backend
suite. Linux CI must be verified against this change's own complete commit SHA,
not inferred from the prior execution commit.

Remaining lifecycle work includes immutable report references and versioned
approval, team arbitration, remediation/retest linkage, independently admitted
schedules, CV execution, streaming metrics and runnable exports. This preview is
not completion of the overall platform.