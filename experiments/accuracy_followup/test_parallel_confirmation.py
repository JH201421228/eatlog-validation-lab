"""Offline wrapper safety checks; synthetic inputs and temporary ledgers only.

Both collectors are replaced before invocation. No SDK, credentials, production
ledger, images, or gold labels are accessed.
"""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_confirmation as wrapper
from budget import BudgetError, Ledger, process_lock
from common import atomic_json, read_json, sha256


class ParallelConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.here = self.root / 'experiment'
        self.here.mkdir()
        self.code = self.root / 'frozen_code.py'
        self.code.write_bytes(b'frozen synthetic code')
        self.freeze = {'candidate_policy': 'flash35_minimal',
                       'confirmation_gold_opened': False,
                       'frozen_files_sha256': {'frozen_code.py': sha256(self.code.read_bytes())}}
        atomic_json(self.here / 'candidate_freeze.json', self.freeze)
        ledger = Ledger(self.here / 'cost_ledger.json')
        ledger.data['entries']['inherited'] = {
            'state': 'usage_settled', 'charged_or_reserved_nanos': 11_726_646_000}
        atomic_json(ledger.path, ledger.data)
        self.freeze['prior_ledger_sha256'] = sha256(ledger.path.read_bytes())
        atomic_json(self.here / 'candidate_freeze.json', self.freeze)
        self.old_factories = wrapper.run_model.Ledger, wrapper.run_model_compare.Ledger

    def execute(self, baseline, candidate):
        with patch.multiple(wrapper, HERE=self.here, ROOT=self.root), \
             patch.object(wrapper.run_model, 'run', baseline), \
             patch.object(wrapper.run_model_compare, 'run', candidate), \
             contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(wrapper.collect())

    def test_both_arms_share_ledger_and_preserve_settled_costs(self):
        seen, active, maximum = [], 0, 0

        async def arm(args):
            nonlocal active, maximum
            module = wrapper.run_model if args.arm == 'baseline' else wrapper.run_model_compare
            ledger = module.Ledger(self.here / 'cost_ledger.json')
            seen.append(ledger)
            self.assertEqual(args.concurrency, 2)
            semaphore = asyncio.Semaphore(args.concurrency)

            async def one(i):
                nonlocal active, maximum
                async with semaphore:
                    identifier = f'{args.arm}_{i}'
                    ledger.reserve(identifier, 'synthetic')
                    active += 1
                    maximum = max(maximum, active)
                    await asyncio.sleep(0)
                    ledger.settle(identifier, {'prompt_token_count': 100,
                                              'candidates_token_count': 100}, 'ok')
                    active -= 1
            await asyncio.gather(*(one(i) for i in range(4)))

        self.execute(arm, arm)
        self.assertIs(seen[0], seen[1])
        self.assertEqual(maximum, 4)
        saved = Ledger(self.here / 'cost_ledger.json')
        self.assertEqual(len(saved.data['entries']), 9)
        self.assertEqual(saved.total_nanos(), 11_726_646_000 + 8 * 280_000)
        self.assertEqual((wrapper.run_model.Ledger, wrapper.run_model_compare.Ledger), self.old_factories)

    def test_failed_arm_reservations_survive_other_arm_reaching_cap(self):
        seen = []

        async def failing(args):
            ledger = wrapper.run_model.Ledger(None)
            seen.append(ledger)
            ledger.reserve('failed_unknown', 'synthetic')
            await asyncio.sleep(0)
            raise RuntimeError('simulated post-reservation failure')

        async def filling(args):
            ledger = wrapper.run_model_compare.Ledger(None)
            seen.append(ledger)
            for i in range(100):
                try:
                    ledger.reserve(f'candidate_{i}', 'synthetic')
                except BudgetError:
                    break
                await asyncio.sleep(0)

        with self.assertRaisesRegex(RuntimeError, 'collector failed'):
            self.execute(failing, filling)
        self.assertIs(seen[0], seen[1])
        saved = Ledger(self.here / 'cost_ledger.json')
        self.assertEqual(saved.total_nanos(), 29_726_646_000)
        self.assertLessEqual(saved.total_nanos(), 30_000_000_000)
        self.assertEqual(saved.data['entries']['failed_unknown']['state'], 'reserved_unknown')
        self.assertEqual(saved.data['entries']['inherited']['charged_or_reserved_nanos'], 11_726_646_000)
        self.assertEqual(len(saved.data['entries']), 37)
        self.assertEqual((wrapper.run_model.Ledger, wrapper.run_model_compare.Ledger), self.old_factories)

    def test_code_freeze_failure_precedes_collectors(self):
        self.code.write_bytes(b'changed')

        async def forbidden(args):
            self.fail('collector must not execute after freeze mismatch')

        before = (self.here / 'cost_ledger.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Frozen input/code changed'):
            self.execute(forbidden, forbidden)
        self.assertEqual((self.here / 'cost_ledger.json').read_bytes(), before)

    def test_real_os_lock_rejects_second_owner(self):
        with process_lock(self.root / 'collector.lock'):
            with self.assertRaises((BudgetError, BlockingIOError)):
                with process_lock(self.root / 'collector.lock'):
                    self.fail('second lock owner admitted')

    def test_missing_inherited_ledger_precedes_collectors(self):
        (self.here / 'cost_ledger.json').unlink()

        async def forbidden(args):
            self.fail('collector must not execute without inherited ledger')

        with self.assertRaisesRegex(RuntimeError, 'ledger is missing'):
            self.execute(forbidden, forbidden)
        self.assertFalse((self.here / 'cost_ledger.json').exists())

    def test_changed_inherited_ledger_precedes_collectors(self):
        path = self.here / 'cost_ledger.json'
        data = read_json(path)
        data['entries'] = {}
        atomic_json(path, data)
        changed_bytes = path.read_bytes()

        async def forbidden(args):
            self.fail('collector must not execute with reset or changed ledger')

        with self.assertRaisesRegex(RuntimeError, 'ledger changed; automatic resume prohibited'):
            self.execute(forbidden, forbidden)
        self.assertEqual(path.read_bytes(), changed_bytes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
