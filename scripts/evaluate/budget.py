"""Durable paid-request ledger. Unknown outcomes retain the full reservation.

One process owns the OS lock; one thread-safe ledger is shared by its workers.
Every network generation is preceded by an fsync'ed reservation. A crash leaves
that reservation spent, and sample IDs may never be reserved twice.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

from common import atomic_json, read_json, utc_now

NANOS_PER_USD = 1_000_000_000
HARD_CAP_NANOS = 30 * NANOS_PER_USD
RESERVE_NANOS = 500_000_000  # > published full context + max output: $0.4784128
INPUT_NANOS_PER_TOKEN = 300
OUTPUT_NANOS_PER_TOKEN = 2500
MODEL_MAX_INPUT = 1_048_576
MODEL_MAX_OUTPUT = 65_536


class BudgetError(RuntimeError):
    pass


def usage_cost(usage):
    """Full-price cached input is conservative; missing usage is not zero cost."""
    if not isinstance(usage, dict):
        return None
    prompt, output, thoughts = (usage.get(k) for k in (
        "prompt_token_count", "candidates_token_count", "thoughts_token_count"))
    thoughts = 0 if thoughts is None else thoughts
    if any(type(v) is not int or v < 0 for v in (prompt, output, thoughts)):
        return None
    if usage.get("tool_use_prompt_token_count") not in (None, 0):
        return None
    total = usage.get("total_token_count")
    if total is not None and total != prompt + output + thoughts:
        return None
    if prompt > MODEL_MAX_INPUT or output + thoughts > MODEL_MAX_OUTPUT:
        return None
    return prompt * INPUT_NANOS_PER_TOKEN + (output + thoughts) * OUTPUT_NANOS_PER_TOKEN


@contextmanager
def process_lock(path):
    """A released OS lock survives stale lock files without unsafe deletion."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BudgetError("Another collector owns the budget lock") from exc
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = read_json(path) if self.path.exists() else {
            "schema_version": 1,
            "created_at": utc_now(),
            "currency": "USD",
            "model": "gemini-2.5-flash",
            "hard_cap_nanos": HARD_CAP_NANOS,
            "reservation_nanos": RESERVE_NANOS,
            "input_usd_per_million": 0.30,
            "output_usd_per_million": 2.50,
            "pricing_source": "https://ai.google.dev/gemini-api/docs/pricing",
            "pricing_checked_date": "2026-10-25",
            "entries": {},
        }
        if self.data["hard_cap_nanos"] != HARD_CAP_NANOS:
            raise BudgetError("Unexpected budget configuration")
        if self.total_nanos() > HARD_CAP_NANOS:
            raise BudgetError("Existing ledger exceeds authorized budget")

    def total_nanos(self):
        return sum(e["charged_or_reserved_nanos"] for e in self.data["entries"].values())

    def reserve(self, identifier, request_sha256):
        with self.lock:
            if identifier in self.data["entries"]:
                raise BudgetError("Sample already attempted; automatic retries prohibited")
            if self.total_nanos() + RESERVE_NANOS > HARD_CAP_NANOS:
                raise BudgetError("US$30 hard budget reached")
            self.data["entries"][identifier] = {
                "reserved_at": utc_now(), "request_sha256": request_sha256,
                "state": "reserved_unknown", "charged_or_reserved_nanos": RESERVE_NANOS,
            }
            atomic_json(self.path, self.data)

    def settle(self, identifier, usage, outcome):
        with self.lock:
            entry = self.data["entries"][identifier]
            if entry["state"] != "reserved_unknown":
                raise BudgetError("Reservation already settled")
            cost = usage_cost(usage)
            if cost is not None and cost > RESERVE_NANOS:
                raise BudgetError("Published model bound violated")
            entry.update({"completed_at": utc_now(), "outcome": outcome, "usage": usage})
            if cost is not None:
                entry.update(state="usage_settled", charged_or_reserved_nanos=cost)
            atomic_json(self.path, self.data)

    def summary(self):
        with self.lock:
            entries = list(self.data["entries"].values())
            settled = [e for e in entries if e["state"] == "usage_settled"]
            return {
                "attempted_generations": len(entries),
                "settled_requests": len(settled),
                "unknown_reserved_requests": len(entries) - len(settled),
                "usage_estimated_usd": sum(e["charged_or_reserved_nanos"] for e in settled) / NANOS_PER_USD,
                "charged_or_reserved_usd": self.total_nanos() / NANOS_PER_USD,
                "hard_cap_usd": 30,
                "billing_invoice_verified": False,
            }
