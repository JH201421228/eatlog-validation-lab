"""Materialize request artifacts. This program has no model/API client."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    # Byte-identical to scripts/evaluate/common.py::canonical.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def main():
    original_schema = json.loads((ROOT / "evaluation/response_schema.json").read_text(encoding="utf-8"))
    original_config = json.loads((ROOT / "evaluation/request_config.json").read_text(encoding="utf-8"))
    neutral = (HERE / "arms/neutral_portion/prompt.txt").read_text(encoding="utf-8")
    volume_prompt = neutral + (HERE / "arms/volume_consistency/portion_instructions.txt").read_text(encoding="utf-8")
    (HERE / "arms/volume_consistency/prompt.txt").write_text(volume_prompt,encoding="utf-8")
    volume_schema = copy.deepcopy(original_schema)
    volume_schema["properties"]["portion_evidence"] = {
        "type":"array", "maxItems":5,
        "items": {"type":"object", "properties":{
            "food_index":{"type":"integer","minimum":0},
            "image_index":{"type":"integer","minimum":0,"maximum":0},
            "visual_summary":{"type":"string"},
            "scale_basis":{"type":"string","enum":["readable_mass","recognizable_reference","food_piece_prior","uncertain_container_prior","unavailable"]},
            "method":{"type":"string","enum":["direct_reading","count_piece_mass","volume_density","visual_estimate","unavailable"]},
            "estimated_volume_ml":{"type":["number","null"],"minimum":0},
            "bulk_density_g_per_ml":{"type":["number","null"],"minimum":0},
            "scale_uncertainty":{"type":"string","enum":["low","medium","high"]},
        }, "required":["food_index","image_index","visual_summary","scale_basis","method","estimated_volume_ml","bulk_density_g_per_ml","scale_uncertainty"]}}
    volume_schema["required"] = [*volume_schema["required"], "portion_evidence"]
    index = {}
    for name, prompt, schema in (("neutral_portion",neutral,original_schema),("volume_consistency",volume_prompt,volume_schema)):
        directory = HERE / "arms" / name
        config = copy.deepcopy(original_config)
        config["prompt_sha256"] = digest(prompt.encode("utf-8"))
        config["schema_sha256"] = digest(canonical(schema))
        assert config["thinking_budget"] == 0 and config["max_output_tokens"] == 4096
        for filename, value in (("response_schema.json",schema),("request_config.json",config)):
            (directory / filename).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        index[name] = {"request_config_sha256":digest(canonical(config)), "prompt_sha256":config["prompt_sha256"],
                       "schema_sha256":config["schema_sha256"],"provider_calls":0}
    (HERE / "arms/index.json").write_text(json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(index,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
