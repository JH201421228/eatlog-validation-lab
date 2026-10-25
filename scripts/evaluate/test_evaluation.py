"""Offline tests for safeguards and denominator semantics; no API credentials."""
import json
import tempfile
import unittest
from pathlib import Path

from budget import BudgetError, HARD_CAP_NANOS, Ledger, RESERVE_NANOS, usage_cost
from replay_worker import raw_prediction
from metrics import nutrient_metrics, minimum_confidence_bin


class BudgetTests(unittest.TestCase):
    def test_model_max_is_covered_by_each_reservation(self):
        cost = usage_cost({"prompt_token_count": 1048576, "candidates_token_count": 65536})
        self.assertEqual(cost, 478412800)
        self.assertLess(cost, RESERVE_NANOS)

    def test_unknown_requests_cannot_cross_thirty_dollars(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "ledger.json")
            for i in range(60):
                ledger.reserve(str(i), "hash")
                ledger.settle(str(i), None, "timeout")
            self.assertEqual(ledger.total_nanos(), HARD_CAP_NANOS)
            with self.assertRaises(BudgetError):
                ledger.reserve("61", "hash")

    def test_restart_does_not_repeat_a_crashed_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            Ledger(path).reserve("dish", "hash")
            restarted = Ledger(path)
            self.assertEqual(restarted.total_nanos(), RESERVE_NANOS)
            with self.assertRaises(BudgetError):
                restarted.reserve("dish", "hash")

    def test_usage_charges_thinking_and_full_cached_input(self):
        self.assertEqual(usage_cost({"prompt_token_count": 100, "candidates_token_count": 10,
                                    "thoughts_token_count": 20, "cached_content_token_count": 100,
                                    "total_token_count": 130}), 105000)

    def test_missing_or_inconsistent_usage_retains_reservation(self):
        self.assertIsNone(usage_cost(None))
        self.assertIsNone(usage_cost({"prompt_token_count": 10}))
        self.assertIsNone(usage_cost({"prompt_token_count": 10, "candidates_token_count": 1, "total_token_count": 99}))

    def test_settlement_frees_unused_reservation_but_not_duplicate_id(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "ledger.json")
            ledger.reserve("dish", "hash")
            ledger.settle("dish", {"prompt_token_count": 100, "candidates_token_count": 100}, "response_received")
            self.assertEqual(ledger.total_nanos(), 280000)
            with self.assertRaises(BudgetError):
                ledger.reserve("dish", "hash")


class DishAggregationTests(unittest.TestCase):
    def test_alternatives_are_not_double_counted(self):
        def candidate(group, confidence, grams, kcal):
            return {"food_index": group, "confidence": confidence, "estimated_serving_g": grams,
                    "nutrition_per_100g": {"calories": kcal, "carbs": 1, "protein": 1, "fat": 1}}
        text = json.dumps({"candidates": [candidate(0, .3, 500, 100), candidate(0, .9, 100, 100), candidate(1, .8, 200, 50)]})
        result = raw_prediction(text)
        self.assertEqual(result["totals"]["calories"], 200)
        self.assertEqual(result["totals"]["mass_g"], 300)

    def test_missing_component_is_not_silently_zero(self):
        text = json.dumps({"candidates": [{"food_index": 0, "estimated_serving_g": None}]})
        self.assertEqual(raw_prediction(text)["status"], "incomplete_nutrition")


class MetricTests(unittest.TestCase):
    def test_failures_remain_in_primary_denominator(self):
        metrics = nutrient_metrics([(100, 100), (100, None), (100, 200)], 3)
        self.assertAlmostEqual(metrics["within_15_percent_of_all_selected"], 100 / 3)
        self.assertEqual(metrics["within_15_percent_of_valid_predictions"], 50)
        self.assertEqual(metrics["missing_prediction_count"], 1)
        self.assertEqual(metrics["mae"], 50)

    def test_mape_and_paper_style_percentage_mae_are_distinct(self):
        metrics = nutrient_metrics([(10, 20), (100, 110), (0, 0)], 3)
        self.assertEqual(metrics["mape_percent"], 55)
        self.assertAlmostEqual(metrics["wape_percent_mae_over_mean_truth"], 20 / 110 * 100)
        self.assertEqual(metrics["mape_zero_truth_excluded_count"], 1)

    def test_confidence_bins_use_plate_minimum_and_explicit_boundaries(self):
        for value, expected in [(0, "[0,0.5)"), (.499, "[0,0.5)"), (.5, "[0.5,0.75)"),
                                (.75, "[0.75,0.9)"), (.9, "[0.9,1]"), (1, "[0.9,1]")]:
            self.assertEqual(minimum_confidence_bin({"selected": [{"confidence": 1}, {"confidence": value}]}), expected)
        self.assertEqual(minimum_confidence_bin({"selected": []}), "missing_confidence")


if __name__ == "__main__":
    unittest.main()
