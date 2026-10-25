# Parallel confirmation safety audit

Updated 2026-10-25 after the frozen final confirmation run. The wrapper SHA-256 is `82f30bb3d723b56f0fd798114cda33975b84cc618999e4172ea86a9dbd01e9c1`, matching `candidate_freeze.json`.

## Offline evidence

Six tests in `test_parallel_confirmation.py` passed using synthetic inputs, temporary ledgers, substituted collectors, and a temporary Windows process lock. They did not call an SDK/API, access credentials, open confirmation gold, or read/write the production cost ledger. The cases cover shared-ledger accounting, reservations retained through failure and budget stop, frozen-code mismatch, exclusion of a second lock owner, rejection when the inherited ledger is missing, and rejection when its hash has changed.

The missing-ledger guard is present in `run_confirmation.py`: the wrapper rejects a missing inherited cost ledger before constructing collectors. It also compares the current ledger bytes to the frozen `prior_ledger_sha256` and rejects changed ledgers, so automatic rerun/resume cannot silently start from another budget state. This closes the earlier audit finding that the `Ledger` constructor could otherwise create a zero-cost ledger.

The frozen wrapper injects the same durable, locked `Ledger` object into both unchanged collectors. The single process lock prevents a second owner. The six offline tests verified that costs from both arms survive ledger writes and that a rejected reservation does not erase prior charges. The frozen code/input digests are checked before collection.

## Confirmation-run record

The wrapper's final JSON record includes `all_collectors_returned_without_unhandled_error`. In the actual run it was `true`, with `errors: []` and `maximum_combined_concurrency: 4`. This key reports that both collector coroutines returned without an uncaught exception; it does not mean every selected item received a model response. The two source-missing inputs remain in each arm's 155-row denominator as `not_attempted`. Inspect each response file's status distribution for request-level completeness.

The run used one shared US$30 ledger, made no automatic retry or resume, and did not read confirmation gold. The final ledger summary is recorded in `README.md` and `evaluation/tmp/followup-confirmation.log`. Scoring and the final decision are complete; see `final_decision.json` and `results/confirm/summary.json`. This audit records collection safety and is not itself a model-performance conclusion.

## Scope

These are focused wrapper and budget tests with substituted collectors, not an end-to-end SDK integration test. They verify local locking, freeze/ledger guards, concurrent shared accounting, and failure reservation behavior. They do not validate provider billing invoices or prove that a normally returning collector produced a successful response for every item.
