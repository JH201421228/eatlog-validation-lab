# Prospective analysis linkage fallback — 2026-10-25

## Hypothesis and scope

When a meal request omits its top-level `ai_call_log_id`, explicit submitted food
candidate IDs can sometimes identify one owned parent call without guessing.
Preserving that existing relation should improve future linkage completeness.
It does not measure full acceptance of the AI result, identify entry method or
tutorial intent, demonstrate improved retention, or repair historical records.
It is independent of photo accuracy evaluation and changes no AI nutrition math.

BE branch: `codex/analysis-link-fallback-20261025`, based on local main
`5b77e1d59e320fd2c4f84650d103bd4b1c2c8ab0`. Before editing, tracked files were
clean; existing untracked `.claude/` and `diag_send_push.py` were preserved.

## Deterministic rule

Use the existing explicit nonnull call ID validation unchanged. Otherwise, infer
a call relation only if every saved item includes an existing owned candidate,
every candidate has an existing parent call, and all parents are the same call
with `user_id` equal to the saving user's ID. Unknown parent ownership is
insufficient. No names, images, timestamps, or nearest-call matching is used.

The existing schema normalizes local/manual candidate keys to `None`. A manual
item or item without candidate ID therefore makes the fallback skip the whole
meal conservatively, including mixed AI/manual meals. No fallback is performed
on later meal edits. Existing selection marking remains unchanged.

No schema migration is required: this uses the existing nullable meal FK. At
implementation handoff, no commit/push/merge/deployment had occurred. The parent
subsequently completed the authorized deployment; see deployment.json for CI,
commit and public health evidence. No historical backfill, FE or production
configuration changes, or analytics-site access were performed.

## Before / after evidence

Existing meal analytics and meal API baseline: **33 passed** in 7.49 s.

The new positive regression was first run against unchanged production code and
failed as expected: saved `ai_call_log_id` was `None` instead of the explicit
candidate's seeded parent ID. This was a synthetic SQLite/mock request.

After the implementation, the analytics, meals, and multi-image API selection
passed: **88 cases in 27.95 s** (including both positive parameters). The final result
is recorded in `results.json`. Existing warnings are python-jose's deprecated
`datetime.utcnow()` usage. No new lint/typecheck configuration was found in BE.

Regression cases: one owned candidate; multiple candidates from one owned call;
multiple parent calls; foreign candidate; nonexistent candidate; null parent FK;
unknown parent owner; local/manual candidate; missing candidate ID; explicit
owned/missing/foreign call IDs retain existing behavior; existing old-client
requests remain unlinked. Positive cases assert `entry_method` and tutorial
status remain unknown.

## Safe reproduction

Run `powershell -NoProfile -ExecutionPolicy Bypass -File ./run_tests.ps1` from
this directory (the flag applies only to this process). It uses BE's checked-in virtualenv and an
empty temporary working directory, so the relative `.env` settings file is not
loaded. It sets SQLite/mock and disables migrations, request logging, and
background jobs. Existing conftest fixtures supply in-memory SQLite, mock social
verification, mock AI, and temporary local storage. Explicit pytest root and
conftest bounds avoid scanning inaccessible ancestor directories. An initial
discovery attempt without these bounds failed before collection; the bounded
baseline and subsequent checks passed.

No raw auth tokens, credentials, user data, or production DB output are stored.
The available aggregate snapshot (98 unknown + 88 unlinked of 257) cannot tell
how many historical or future requests meet this fallback's conditions. It is
not evidence that those categories will shrink by any specified amount.
