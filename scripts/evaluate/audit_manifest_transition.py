"""Independently check a source-only amendment against already requested images."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import EVAL, atomic_json, read_json, read_jsonl, sample_id, sha256, utc_now

SOURCE_FIELDS = {"camera_view", "source_key", "source_url", "source_object", "frame_index", "frame_timestamp_s"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--amended", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=EVAL / "evidence/source_amendment_audit.json")
    args = parser.parse_args()
    previous = {sample_id(row): row for row in read_jsonl(args.previous)}
    amended = {sample_id(row): row for row in read_jsonl(args.amended)}
    if set(previous) != set(amended):
        raise RuntimeError("Source amendment changed selected sample IDs")
    requested = {raw["sample_id"] for path in (EVAL / "raw_responses").glob("*.json")
                 if "latency_ms" in (raw := read_json(path))}
    changes = []
    metadata_enrichments = 0
    version_bookkeeping_changes = 0
    for identifier, old in previous.items():
        new = amended[identifier]
        changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
        if "selection_version" in changed:
            if new["selection_version"] != 3:
                raise RuntimeError("Unexpected selection version")
            changed.remove("selection_version")
            version_bookkeeping_changes += 1
        # v2 side objects had unresolved metadata; v3 adds GCS generation/MD5.
        # URL/key/view and image bytes remain independently checked.
        if "source_object" in changed and old.get("source_object") is None and isinstance(new.get("source_object"), dict):
            changed.remove("source_object")
            metadata_enrichments += 1
        if changed - SOURCE_FIELDS:
            raise RuntimeError(f"Non-source fields changed for {identifier}: {sorted(changed - SOURCE_FIELDS)}")
        if changed:
            if identifier in requested:
                raise RuntimeError("An already requested sample was changed")
            changes.append({"sample_id": identifier, "changed_fields": sorted(changed),
                            "previous_source_url": old["source_url"], "amended_source_url": new["source_url"]})
    result = {"checked_at": utc_now(), "previous_manifest_sha256": sha256(args.previous.read_bytes()),
              "amended_manifest_sha256": sha256(args.amended.read_bytes()), "sample_count": len(previous),
              "paid_sample_count_at_audit": len(requested), "changed_sample_count": len(changes),
              "already_requested_changed_samples": 0, "labels_or_groups_changed": False,
              "source_object_metadata_enrichments": metadata_enrichments,
              "selection_version_bookkeeping_changes": version_bookkeeping_changes,
              "selection_or_split_changed": False, "changes": changes}
    atomic_json(args.output, result)
    print({"samples": len(previous), "source_changes": len(changes), "already_requested_changed": 0})


if __name__ == "__main__":
    main()
