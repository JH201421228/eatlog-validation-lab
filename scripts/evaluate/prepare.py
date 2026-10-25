"""Pin code and production prompt without touching team repositories or secrets."""
from __future__ import annotations

import argparse
import ast
import io
import subprocess
import tarfile
from pathlib import Path

from common import ROOT, EVAL, atomic_json, canonical, sha256, utc_now

REFS = {
    "baseline_ai": ("AI", "9ce6e9ee029d5891f92b2488672404d861c37ec1", "ai-server/app"),
    "improved_ai": ("AI", "f1bf0e6cc81ee5a5befab8b32d1043cfd7cbde2a", "ai-server/app"),
    "baseline_be": ("BE", "dc11453", "app"),
    "improved_be": ("BE", "8742e1b", "app"),
}


def git(repo, *args):
    path = ROOT.parent / repo
    return subprocess.check_output(["git", "-c", f"safe.directory={path.as_posix()}", "-C", str(path), *args])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--freeze", type=Path, default=EVAL / "manifest_freeze.json")
    args = parser.parse_args()
    EVAL.mkdir(exist_ok=True)
    sources = {}
    for name, (repo, ref, tracked_path) in REFS.items():
        full = git(repo, "rev-parse", ref).decode().strip()
        archive = git(repo, "archive", full, tracked_path)
        target = EVAL / "tmp" / "code" / name
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            files = {member.name: sha256(tar.extractfile(member).read())
                     for member in tar.getmembers() if member.isfile()}
            tar.extractall(target, filter="data")
        sources[name] = {"repository": repo, "commit": full, "archive_sha256": sha256(archive),
                         "tracked_files_sha256": files}
    improved = EVAL / "tmp/code/improved_ai/ai-server/app"
    tree = ast.parse((improved / "services/vision.py").read_text(encoding="utf-8"))
    prompt = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ANALYZE_PROMPT" for t in node.targets))
    prompt = prompt.replace("__MAX_CANDIDATES__", "3").replace("__MAX_FOODS__", "5")
    namespace = {}
    exec(compile((improved / "schemas/model_response.py").read_text(encoding="utf-8"), "model_response.py", "exec"), namespace)
    schema = namespace["ANALYZE_RESPONSE_SCHEMA"]
    config = {
        "model": "gemini-2.5-flash", "temperature": 0, "seed": 20260722,
        "thinking_budget": 0, "max_output_tokens": 4096,
        "http_timeout_ms": 90000, "sdk_attempts": 1,
        "max_counted_input_plus_schema_margin": 20000,
        "schema_extra_margin_tokens": 4096,
        "max_foods": 5, "max_candidates_per_food": 3,
        "grounding": False, "user_text": None, "image_transform": "none",
        "one_generation_replayed_for_both_versions": True,
        "prompt_sha256": sha256(prompt.encode("utf-8")), "schema_sha256": sha256(canonical(schema)),
    }
    for filename, value in (("source_index.json", sources), ("request_config.json", config), ("response_schema.json", schema)):
        path = EVAL / filename
        if path.exists() and path.read_bytes() and __import__("json").loads(path.read_text(encoding="utf-8")) != value:
            raise RuntimeError(f"Refusing to change frozen {filename}")
        atomic_json(path, value)
    (EVAL / "prompt.txt").write_text(prompt, encoding="utf-8")
    if args.manifest:
        identity = {"manifest_path": str(args.manifest.relative_to(ROOT)).replace("\\", "/"),
                    "manifest_sha256": sha256(args.manifest.read_bytes()), "frozen_at": utc_now(),
                    "request_config_sha256": sha256(canonical(config))}
        path = args.freeze
        if path.exists():
            from common import read_json
            old = read_json(path)
            if old["manifest_sha256"] != identity["manifest_sha256"]:
                raise RuntimeError("Manifest changed after freeze")
        else:
            atomic_json(path, identity)
    print({"code_snapshots": len(sources), "request_config_sha256": sha256(canonical(config)), "paid_calls_in_this_command": 0})


if __name__ == "__main__":
    main()
