# Superseded audit snapshots — do not score these as the final dataset

`v1_before_quality_audit/` preserves the first frozen list and partial downloads. It includes Cafe 2 zero-placeholder nutrition totals and empty-plate/inconsistent source labels that were later rejected using source-only QC. These labels must not be used as final food nutrition gold.

`v2_before_source_resolution/` preserves the valid-label selection before resolving missing camera-A source objects. No dish, inferred group, label, or split changes in v3. Only officially existing camera sources are resolved; frame index remains 0.

The current fixed dataset is `../selection_manifest_v3.jsonl`; its downloaded file hashes and statuses are `../manifest.jsonl`. Historical artifacts are retained to disclose protocol timing and changes, not to erase failed attempts.
