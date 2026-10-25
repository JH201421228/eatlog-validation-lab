"""Deterministic public-data lookup; no truth, image ids or network access."""
from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from types import SimpleNamespace

NUTRIENTS = ("calories", "carbs", "protein", "fat")
ALIASES = {
    "닭가슴살": "닭고기가슴", "닭다리": "닭고기다리", "닭날개": "닭고기날개",
    "컬리플라워": "콜리플라워", "방울토마토": "토마토방울토마토",
}
PREFIXES = {
    "구운": "roasted", "삶은": "boiled", "찐": "steamed", "데친": "blanched",
    "볶은": "stir_fried", "튀긴": "fried", "생": "raw",
}
SUFFIXES = {
    "구이": "roasted", "스테이크": "roasted", "삶은것": "boiled",
    "찐것": "steamed", "데친것": "blanched", "볶음": "stir_fried",
    "튀김": "fried", "생것": "raw",
}
# Do not let a broad commodity name absorb nutritionally distinct body parts.
EXPLICIT_PARTS = {"잎", "줄기", "싹", "씨", "씨앗", "난황", "난백", "내장", "껍질", "알", "간"}


def norm(text):
    return re.sub(r"\s+", "", str(text or "")).lower()


def quality_reason(row):
    if row.get("base_unit") != "g" or row.get("base_amount") != 100:
        return "not_100g_basis"
    if row.get("macros_estimated"):
        return "estimated_macros"
    values = [row.get(k) for k in NUTRIENTS]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in values):
        return "invalid_numeric"
    if values[0] > 900 or any(x > 100 for x in values[1:]) or sum(values[1:]) > 105:
        return "impossible_density"
    return None


def source_state(text):
    text = norm(text)
    # Dry-then-boiled is the hydrated final food; boiled-then-dried is dry.
    if text == "말린것을삶은것":
        return "boiled"
    for token, state in [("구운것", "roasted"), ("삶은것", "boiled"), ("찐것", "steamed"),
                         ("데친것", "blanched"), ("볶은것", "stir_fried"),
                         ("튀긴것", "fried"), ("생것", "raw")]:
        if text == token or text.startswith(token + "("):
            return state
    return None


def parse_query(text):
    value = norm(text)
    state = None
    # A prefix must leave an ingredient, and that full remainder must match.
    for prefix, method in PREFIXES.items():
        if value.startswith(prefix) and len(value) > len(prefix):
            value, state = value[len(prefix):], method
            break
    for suffix, method in SUFFIXES.items():
        if value.endswith(suffix) and len(value) > len(suffix):
            if state and state != method:
                return value, "conflicting"
            value, state = value[:-len(suffix)], method
            break
    return ALIASES.get(value, value), state


def source_synonyms(name):
    """Only source-declared parentheses, with ambiguous aliases rejected later."""
    result = {norm(name)}
    match = re.fullmatch(r"([^()]+)\(([^()]+)\)", name)
    if match:
        result.update(norm(x) for x in match.groups())
    return result


class Reference:
    def __init__(self, rows, normalize_name, priority):
        self.normalize_name, self.priority = normalize_name, priority
        self.exact = defaultdict(list)
        self.context = defaultdict(dict)
        self.alias_targets = defaultdict(set)
        for row in rows:
            self.exact[row["normalized_name"]].append(row)
            if row["reference_type"] != "variant" or quality_reason(row):
                continue
            state = source_state(row["source_state"])
            if state is None:
                continue
            for key in row["generic_keys"]:
                canonical = norm(key[1])
                # Explicitly retain anatomically requested parts only.
                parts = {norm(re.sub(r"\(.*?\)", "", s)) for s in row["source_levels"][1:]}
                if any(part in EXPLICIT_PARTS and part not in canonical for part in parts):
                    continue
                self.context[(canonical, state)][row["external_id"]] = row
                for alias in source_synonyms(key[1]):
                    self.alias_targets[alias].add(canonical)

    def exact_match(self, name, quality=False):
        rows = self.exact.get(self.normalize_name(name), [])
        eligible = [r for r in rows if not quality or quality_reason(r) is None]
        if not eligible:
            return None, {"reason": "quality_rejected" if rows else "no_exact_match"}
        chosen = min(eligible, key=lambda r: self.priority(SimpleNamespace(**r)))
        return SimpleNamespace(**chosen), {
            "reason": "quality_exact" if quality else "current_exact",
            "reference_codes": chosen.get("source_food_codes", [chosen["external_id"]]),
            "same_name_rows": len(rows), "matched_name": chosen["name"],
        }

    def match(self, candidate, arm):
        if arm in {"current_exact", "quality_exact"}:
            return self.exact_match(candidate.food_name, arm == "quality_exact")
        if arm != "state_aware":
            raise ValueError(arm)
        if candidate.has_sauce:
            return None, {"reason": "sauce_not_in_reference"}
        query, state = parse_query(candidate.food_name)
        targets = self.alias_targets.get(query, {query})
        if len(targets) != 1:
            return None, {"reason": "ambiguous_source_synonym"}
        canonical = next(iter(targets))
        assumed = state is None
        if assumed:
            raw = list(self.context.get((canonical, "raw"), {}).values())
            if not raw or any(r["source_category"] != "과일류" for r in raw):
                return None, {"reason": "unspecified_cooking_state"}
            state = "raw"
        rows = list(self.context.get((canonical, state), {}).values())
        if not rows:
            return None, {"reason": "no_same_state_reference", "query": query, "requested_state": state}
        value = dict(rows[0])
        value.update({k: round(statistics.fmean(r[k] for r in rows), 2) for k in NUTRIENTS})
        value.update(name=f"{canonical} [{state}]", external_id=f"state:{canonical}:{state}",
                     macros_estimated=False, reference_type="state_mean")
        return SimpleNamespace(**value), {
            "reason": "fruit_raw_assumption" if assumed else "explicit_state_match",
            "query": query, "matched_name": value["name"], "requested_state": state,
            "reference_codes": sorted(r["external_id"] for r in rows),
            "reference_kcal_range": [min(r["calories"] for r in rows), max(r["calories"] for r in rows)],
        }
