# Parallel confirmation safety audit

2026-10-25. Offline review of `run_confirmation.py`, both unchanged collectors,
and `scripts/evaluate/budget.py` plus `common.py`.

`test_parallel_confirmation.py` ran using `AI/ai-server/.venv/Scripts/python.exe`:
4 tests passed in 0.255 seconds. Tests invoke the real wrapper with both collector
functions replaced, real temporary ledgers, synthetic freeze inputs, and a real
temporary Windows OS lock. They never invoke an SDK or API, access credentials,
open gold labels, or read/write the production cost ledger.

Verified:

- Both arms obtain the exact same Ledger object; two requests per arm reach four
  simulated simultaneous requests. Settled entries from both arms and inherited
  charges survive every ledger rewrite.
- With synthetic inherited charged/reserved usage of USD 11.726646, an arm failure
  after reservation and another arm repeatedly reserving stop at USD 29.726646.
  The next USD 0.50 reservation is rejected. The failed request retains its full
  reservation, prior costs survive, and injected constructors are restored.
- A frozen code hash mismatch rejects collection before either collector runs.
- A second owner cannot obtain the same real Windows process lock.

Review findings reported to coordinator:

- The wrapper initially lacked the existing-ledger guard in collector `main()`.
  `Ledger` creates a zero-cost ledger if its file is absent, so the wrapper must
  reject a missing cost ledger before API collection. Coordinator owns this fix.
- Freeze checking verifies every listed digest but does not enforce the list's
  completeness. The coordinator must include both collectors, wrapper, budget and
  common helpers, prompts/config/schema, and frozen selection/input/download
  manifests. Image hashes are checked by collectors against the download manifest.
- `joint_confirmation_complete` means both collector coroutines returned without
  uncaught exceptions; it does not prove all selected requests succeeded. Budget
  stops and per-request handled errors can return normally. Inspect response
  completeness before scoring.
- Wrapper output records exception class names only. Collector result files and
  reservations remain durable, but uncaught exception messages/tracebacks are not
  retained by this wrapper. This limits diagnosis, not the budget guard.

Within one asyncio event loop, ledger writes and summary writes are synchronous;
they do not interleave halfway through `atomic_json`. Ledger reserve/settle also
hold an RLock. Shared-object injection prevents stale per-arm ledger snapshots
from overwriting other arms' charges. Every paid generation follows a durable
reservation. Unknown usage and failed result persistence keep the reservation.

Scope: these are focused wrapper/budget tests with substituted collectors, not an
end-to-end SDK integration test. No external pricing or model limits were checked.
