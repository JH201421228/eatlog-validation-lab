import copy
import math
import unittest
from calibrator import FEATURE_NAMES, apply_candidates, feature_input, features, validate_features, fit, predict_mass


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.row = {'sample_id': 'ignored', 'status': 'success', 'totals': {'mass_g': 100., 'calories': 120.},
                    'selected': [{'food_name': '볶음밥', 'grams': 100., 'count': 1., 'confidence': .9,
                                  'estimated_serving': 1., 'nutrition_per_unit': {'calories': 120., 'carbs': 20., 'protein': 5., 'fat': 2.}}]}

    def test_allowlist_rejects_labels_and_identifiers(self):
        data = feature_input(self.row)
        self.assertTrue(validate_features(data))
        for key in ('truth', 'sample_id', 'ingredients', 'camera_view', 'date'):
            self.assertFalse(validate_features({**data, key: 'forbidden'}))
        changed = copy.deepcopy(self.row)
        changed.update(sample_id='different', truth={'mass_g': 999999}, camera_view='other')
        self.assertEqual(features(feature_input(self.row)), features(feature_input(changed)))

    def test_density_preserved_and_factor_clipped(self):
        model = {'target': 'log_mass_g', 'feature_names': FEATURE_NAMES, 'factor_bounds': [.5, 2.], 'intercept': 20.,
                 'coef': [0.] * len(FEATURE_NAMES), 'mean': [0.] * len(FEATURE_NAMES), 'std': [1.] * len(FEATURE_NAMES)}
        ai = {'sample_id': 'ignored', 'status': 'success', 'candidates': [{'food_name': '볶음밥',
              'estimated_serving_g': 100., 'count': 2., 'count_unit': '개', 'food_index': 0,
              'confidence': .9, 'nutrition_per_100g': {'calories': 120.}}]}
        result = apply_candidates(model, self.row, ai)
        self.assertEqual(result['candidates'][0]['estimated_serving_g'], 200.)
        self.assertTrue(result['calibration']['clipped'])
        for key in ('count', 'count_unit', 'food_index', 'confidence', 'nutrition_per_100g'):
            self.assertEqual(result['candidates'][0][key], ai['candidates'][0][key])
        protected = copy.deepcopy(self.row)
        protected['selected'][0]['package_present'] = True
        self.assertFalse(apply_candidates(model, protected, ai)['calibration']['applied'])
        self.assertEqual(apply_candidates(model, protected, ai)['candidates'], ai['candidates'])
        model.update(target='linear_mass_g', intercept=-100.)
        result = apply_candidates(model, self.row, ai)
        self.assertFalse(result['calibration']['applied'])
        self.assertEqual(result['candidates'], ai['candidates'])

    def test_weighted_log_intercept_uses_training_weights(self):
        data = feature_input(self.row)
        x = features(data)
        model = fit([x, x, x], [10., 20., 100.], 10, 'weighted_log_mass')
        expected_log = (.5 * math.log(10) + math.log(20) + 4 * math.log(100)) / 5.5
        self.assertAlmostEqual(model['intercept'], expected_log)
        self.assertAlmostEqual(predict_mass(model, data)['mass_g'], math.exp(expected_log))

    def test_alternative_label_protects_whole_plate(self):
        model = {'target': 'log_mass_g', 'feature_names': FEATURE_NAMES, 'factor_bounds': [.5, 2.], 'intercept': 20.,
                 'coef': [0.] * len(FEATURE_NAMES), 'mean': [0.] * len(FEATURE_NAMES), 'std': [1.] * len(FEATURE_NAMES)}
        ai = {'sample_id': 'ignored', 'status': 'success', 'candidates': [
            {'estimated_serving_g': 100., 'package': None, 'label': None},
            {'estimated_serving_g': 120., 'package': {}, 'label': None}]}
        result = apply_candidates(model, self.row, ai)
        self.assertEqual(result['calibration'], {'applied': False, 'reason': 'protected_alternative_label'})
        self.assertEqual(result['candidates'], ai['candidates'])
        ai['candidates'][1].update(package=None, label={'source': 'label'})
        self.assertEqual(apply_candidates(model, self.row, ai)['candidates'], ai['candidates'])


if __name__ == '__main__':
    unittest.main()
