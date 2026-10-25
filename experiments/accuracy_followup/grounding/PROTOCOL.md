# MFDS density grounding — exploratory protocol v1

This is a follow-up after the original 1,000-dish evaluation was scored. It is
an exploratory reuse of those outputs, **not a fresh holdout**. Rules below are
fixed before this experiment's predictions are scored. Model food names and
grams may be inspected while implementing the retrieval interface; Nutrition5k
ingredient labels and its source nutrition tables must never enter retrieval.

## Reference and isolation

- Use BE `scripts/data/mfds_material.jsonl`, SHA256
  `5161faa96a5250b2465188f377ddf3021a5dd15a39127ba6ba524ba9b86652c5`.
  The checked-in 40-item seed is explicitly approximate mock data and excluded.
- Reproduce current material importer transformations and `_match_priority` in
  an isolated process with `DATABASE_URL=sqlite://`. Never open a DB session.
- Store only normalized public nutrition fields, taxonomy and provenance.
  No `.env`, API keys, request URLs, production records or private data copied.
- This reference is a **partial public material DB**, not a production DB dump.
  Current-code results with it cannot be called actual production accuracy.
- No API requests. Current AI-normalized candidate JSONL is reused unchanged.
  Label/printed nutrition priority, group selection, grams and BE rounding stay
  unchanged. The experiment changes only the supplied matched DB row.

## Three arms

1. `current_exact`: current exact normalized name matching and current importer
   raw-first generic averages. DB ids are assigned in importer insertion order;
   production id order and other tables may differ.
2. `quality_exact`: same exact lookup and priority, but reject non-g basis,
   estimated macros, nonfinite/negative values, >900 kcal/100g, any macro >100g
   and macro sum >105g/100g. The 5g tolerance permits source rounding; these are
   source quality checks, not parameters fitted to test labels.
3. `state_aware`: quality checks plus exact single-ingredient lookup with cooking
   state. Known Korean cooking prefixes/suffixes map only to the same source
   state (e.g. 구운→구운것). Missing source state falls back to the AI estimate.
   No broad substring/fuzzy matching, embedding search or model-based translation.
   Source parenthetical synonyms and a small declared lexical alias dictionary
   are allowed. Unspecified state is accepted only for plain fruit names as raw,
   an explicit assumption; other unspecified-state foods fall back. Candidates
   marked with sauce fall back because a raw ingredient reference omits sauce.
   Unrequested leaf/seed/offal/egg-part records are excluded from generic means.
   Means are unweighted across remaining public source records; varieties and
   regional recipes remain a limitation.

The existing `improved_no_db` result is a fourth **reference comparison**, not
another changed arm. No coefficient is learned from Nutrition5k truth.

## Evaluation

Freeze input, reference, implementation and prediction hashes before loading
truth. Score all 1,000 selected ids, retaining missing/failed rows in coverage.
Report valid-pair MAE, MAPE, WAPE, within-15% rate, changed/better/worse counts,
DB coverage/fallback, and paired bootstrap MAE differences. Confirm every arm's
grams and candidate selections equal the no-DB baseline. Report failures and
all negative results. No arm is automatically approved for deployment.

The underlying food source is Korea's MFDS/RDA/NIFS material database; the
evaluation labels use Nutrition5k ingredient weights and USDA-based nutrition.
Different origins, food varieties, cooking fat and dish composition can cause
disagreement even with correct retrieval. Image portion errors remain unchanged.
