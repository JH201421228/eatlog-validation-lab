"""Semantic safety tests for the experimental lookup, not model accuracy tests."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from grounding import Reference, norm, parse_query, quality_reason, source_state


class GroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [json.loads(s) for s in Path(__file__).with_name("reference.jsonl").read_text(encoding="utf-8").splitlines()]
        cls.reference = Reference(rows, norm, lambda r: r.id)

    def match(self, name, sauce=False):
        return self.reference.match(SimpleNamespace(food_name=name, has_sauce=sauce), "state_aware")

    def test_cooking_state_and_part(self):
        match, trace = self.match("구운 닭가슴살")
        self.assertIsNotNone(match)
        self.assertEqual(trace["requested_state"], "roasted")
        self.assertEqual(match.calories, 164)
        self.assertNotEqual(match.calories, 106)  # Raw chicken breast reference.

    def test_uncertain_state_keeps_ai(self):
        for name in ("닭가슴살", "파스타", "밥", "브로콜리", "샐러드"):
            with self.subTest(name=name):
                self.assertIsNone(self.match(name)[0])

    def test_composite_and_sauce_do_not_become_single_ingredient(self):
        self.assertIsNone(self.match("닭가슴살 샐러드")[0])
        self.assertIsNone(self.match("구운 닭가슴살", sauce=True)[0])
        self.assertIsNone(self.match("사과 파이")[0])

    def test_fruit_raw_assumption_is_logged(self):
        row, trace = self.match("사과")
        self.assertIsNotNone(row)
        self.assertEqual(trace["reason"], "fruit_raw_assumption")

    def test_source_declared_alias(self):
        row, trace = self.match("데친 콜리플라워")
        self.assertEqual(row.calories, 26)
        self.assertEqual(trace["requested_state"], "blanched")

    def test_missing_same_state_no_fuzzy_fallback(self):
        self.assertIsNone(self.match("구운 콜리플라워")[0])

    def test_hydration_order_matters(self):
        self.assertEqual(source_state("말린것을 삶은것"), "boiled")
        self.assertIsNone(source_state("삶아서 말린것"))

    def test_quality_rejects_units_estimates_and_nonfinite(self):
        valid = dict(base_unit="g", base_amount=100, macros_estimated=False, calories=100, carbs=10, protein=10, fat=2)
        self.assertIsNone(quality_reason(valid))
        for changes in ({"base_unit": "ml"}, {"calories": float("nan")}, {"protein": float("inf")},
                        {"fat": True}, {"carbs": -1}, {"calories": 901}, {"macros_estimated": True},
                        {"carbs": 90, "protein": 20}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(quality_reason({**valid, **changes}))

    def test_prediction_food_and_grams_unchanged(self):
        directory = Path(__file__).with_name("results")
        baseline = [json.loads(s) for s in (directory / "no_db.jsonl").read_text(encoding="utf-8").splitlines()]
        for arm in ("current_exact", "quality_exact", "state_aware"):
            rows = [json.loads(s) for s in (directory / f"{arm}.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1000)
            for original, changed in zip(baseline, rows):
                self.assertEqual(original["sample_id"], changed["sample_id"])
                fields = lambda r: [(x["food_name"], x["grams"]) for x in r.get("selected", [])]
                self.assertEqual(fields(original), fields(changed))


if __name__ == "__main__":
    unittest.main()
