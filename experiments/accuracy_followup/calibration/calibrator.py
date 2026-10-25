"""Small learned mass calibration. Inference uses only normalized model output.

Fit uses NumPy; prediction has no third-party dependencies or service calls.
"""
from __future__ import annotations
import copy
import hashlib
import math
import re

NGRAM_DIM = 64
FEATURE_NAMES = ['log_predmass', 'log_predkcal_per_g', 'foodgroup_count',
                 'confidence_min', 'confidence_mean', 'log_known_count_sum', 'count_present_fraction'] + [f'ko_ngram_{i}' for i in range(NGRAM_DIM)]
ALPHAS = [10, 100, 1000]
FACTOR_MIN, FACTOR_MAX = .5, 2.
NUTRIENTS = ('calories', 'carbs', 'protein', 'fat')


def finite(x):
    return type(x) in (float, int) and math.isfinite(x)


def feature_input(row):
    if row.get('status') != 'success':
        return None
    foods = row.get('selected') or []
    if not foods or any(f.get('package_present') or f.get('printed_kcal') is not None or f.get('grounded_label_present') for f in foods):
        return None
    totals = row.get('totals') or {}
    return {'predicted_mass_g': totals.get('mass_g'), 'predicted_calories_kcal': totals.get('calories'),
            'foods': [{key: f.get(key) for key in ('food_name', 'confidence', 'grams', 'count')} for f in foods]}


def validate_features(data):
    """Allowlist prevents IDs, labels, camera/time and ingredient truth entering features."""
    if not isinstance(data, dict) or set(data) != {'predicted_mass_g', 'predicted_calories_kcal', 'foods'}:
        return False
    if not finite(data['predicted_mass_g']) or data['predicted_mass_g'] <= 0:
        return False
    if not finite(data['predicted_calories_kcal']) or data['predicted_calories_kcal'] < 0:
        return False
    if not isinstance(data['foods'], list) or not data['foods']:
        return False
    for food in data['foods']:
        if not isinstance(food, dict) or set(food) != {'food_name', 'confidence', 'grams', 'count'}:
            return False
        if not isinstance(food['food_name'], str) or not 1 <= len(food['food_name']) <= 256:
            return False
        if not finite(food['confidence']) or not 0 <= food['confidence'] <= 1:
            return False
        if not finite(food['grams']) or food['grams'] <= 0:
            return False
        if food['count'] is not None and (not finite(food['count']) or food['count'] < 0):
            return False
    return True


def features(data):
    if not validate_features(data):
        return None
    mass, kcal, foods = data['predicted_mass_g'], data['predicted_calories_kcal'], data['foods']
    confidence = [f['confidence'] for f in foods]
    # A model estimate of zero kcal is valid; floor only this logarithmic feature.
    values = [math.log(mass), math.log(max(kcal / mass, 1e-6)), len(foods), min(confidence),
              sum(confidence) / len(confidence), math.log1p(sum(f['count'] for f in foods if f['count'] is not None)),
              sum(f['count'] is not None for f in foods) / len(foods)]
    grams = sum(f['grams'] for f in foods)
    hashed = [0.] * NGRAM_DIM
    for food in foods:
        # Korean-character composition only; no ID or source metadata is accepted.
        name = ''.join(re.findall(r'[가-힣]', food['food_name']))
        ngrams = [name[i:i+n] for n in (2, 3) for i in range(max(0, len(name) - n + 1))]
        for text in ngrams:
            digest = hashlib.sha256(('mass-ko-v1|' + text).encode()).digest()
            bucket = int.from_bytes(digest[:4], 'big') % NGRAM_DIM
            sign = 1 if digest[4] & 1 else -1
            hashed[bucket] += sign * food['grams'] / grams / len(ngrams)
    return values + hashed


def fit(inputs, target_masses, alpha, family='log_mass'):
    import numpy as np
    x = np.asarray(inputs, dtype=float)
    if family not in ('log_mass', 'linear_mass', 'weighted_log_mass'):
        raise ValueError('Unknown mass target family')
    y = np.asarray(target_masses, dtype=float)
    masses = y.copy()
    if family in ('log_mass', 'weighted_log_mass'):
        y = np.log(y)
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std < 1e-12] = 1.
    z = (x - mean) / std
    weights = np.clip(masses / np.median(masses), .5, 4.) if family == 'weighted_log_mass' else np.ones(len(y))
    zcenter = np.average(z, axis=0, weights=weights)
    ycenter = np.average(y, weights=weights)
    centered = z - zcenter
    coef = np.linalg.solve(centered.T @ (weights[:, None] * centered) + alpha * np.eye(z.shape[1]), centered.T @ (weights * (y - ycenter)))
    intercept = ycenter - zcenter @ coef
    return {'version': 1, 'target': family + '_g', 'family': family, 'alpha': alpha, 'feature_names': FEATURE_NAMES,
            'ngram_dim': NGRAM_DIM, 'factor_bounds': [FACTOR_MIN, FACTOR_MAX],
            'mean': mean.tolist(), 'std': std.tolist(), 'coef': coef.tolist(), 'intercept': float(intercept)}


def predict_mass(model, data):
    x = features(data)
    if x is None:
        return None
    if model['feature_names'] != FEATURE_NAMES or model['factor_bounds'] != [FACTOR_MIN, FACTOR_MAX]:
        raise ValueError('Calibration model schema mismatch')
    linear = model['intercept'] + sum(c * (value - mean) / std for c, value, mean, std in zip(model['coef'], x, model['mean'], model['std']))
    estimated = math.exp(max(-20., min(20., linear))) if model['target'] in ('log_mass_g', 'weighted_log_mass_g') else linear
    mass = data['predicted_mass_g']
    if not finite(estimated) or estimated <= 0:
        return {'mass_g': mass, 'factor': 1., 'unclipped_factor': None,
                'clipped': False, 'fallback': True, 'reason': 'nonpositive_or_nonfinite_learned_mass'}
    unclipped = estimated / mass
    factor = max(FACTOR_MIN, min(FACTOR_MAX, unclipped))
    return {'mass_g': mass * factor, 'factor': factor, 'unclipped_factor': unclipped,
            'clipped': factor != unclipped}


def apply_candidates(model, normalized_row, ai_row):
    """Change only candidate mass; actual BE resolves per-unit nutrition and count."""
    if any(candidate.get('package') is not None or candidate.get('label') is not None
           for candidate in (ai_row.get('candidates') or [])):
        original = copy.deepcopy(ai_row)
        original['calibration'] = {'applied': False, 'reason': 'protected_alternative_label'}
        return original
    data = feature_input(normalized_row)
    estimate = predict_mass(model, data) if data else None
    original = copy.deepcopy(ai_row)
    if estimate is None:
        original['calibration'] = {'applied': False, 'reason': 'protected_label_or_missing_features'}
        return original
    if estimate.get('fallback'):
        original['calibration'] = {'applied': False, **estimate}
        return original
    if original.get('status') != 'success' or not original.get('candidates'):
        original['calibration'] = {'applied': False, 'reason': 'missing_ai_candidates'}
        return original
    for candidate in original['candidates']:
        grams = candidate.get('estimated_serving_g')
        if finite(grams) and grams > 0:
            candidate['estimated_serving_g'] = grams * estimate['factor']
    original['calibration'] = {'applied': True, **estimate}
    return original
