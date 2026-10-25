"""One paid image request per frozen sample, with a US$30 fail-closed ledger.

Only this program makes model calls. It never passes truth labels to the model.
Raw responses and original images stay in git-ignored local directories.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import time
from pathlib import Path

from budget import BudgetError, Ledger, process_lock
from common import ROOT, EVAL, atomic_json, canonical, image_path, read_json, read_jsonl, sample_id, sha256, utc_now


def api_key():
    value = os.environ.get("GEMINI_API_KEY")
    if not value:
        from dotenv import dotenv_values
        value = dotenv_values(ROOT.parent / "AI/ai-server/.env").get("GEMINI_API_KEY")
    if not value:
        raise RuntimeError("GEMINI_API_KEY is unavailable")
    return value


async def run(args):
    from google import genai
    from google.genai import types

    config = read_json(EVAL / "request_config.json")
    if config["model"] != "gemini-2.5-flash" or config["max_output_tokens"] != 4096:
        raise RuntimeError("Model/cost configuration differs from authorization")
    frozen = read_json(args.freeze)
    if sha256(args.manifest.read_bytes()) != frozen["manifest_sha256"]:
        raise RuntimeError("Manifest differs from frozen selection")
    if sha256(canonical(config)) != frozen["request_config_sha256"]:
        raise RuntimeError("Request configuration changed after freeze")
    prompt = (EVAL / "prompt.txt").read_text(encoding="utf-8")
    schema = read_json(EVAL / "response_schema.json")
    if sha256(prompt.encode("utf-8")) != config["prompt_sha256"] or sha256(canonical(schema)) != config["schema_sha256"]:
        raise RuntimeError("Frozen prompt/schema mismatch")
    all_rows = read_jsonl(args.manifest)
    ids = [sample_id(row) for row in all_rows]
    if len(set(ids)) != len(ids):
        raise RuntimeError("Duplicate sample IDs")
    # Copy only the image routing fields here; truth is neither logged nor sent.
    selected = [{k: row[k] for k in ("sample_id", "dish_id", "split", "image_path", "image_sha256", "sha256") if k in row}
                for row in all_rows if row["split"] == args.split]
    downloads = {sample_id(row): {k: row.get(k) for k in ("image_path", "image_sha256", "download_status")}
                 for row in read_jsonl(args.download_manifest)}
    if args.limit is not None:
        selected = selected[:args.limit]
    rawdir = EVAL / "raw_responses"
    rawdir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(EVAL / "cost_ledger.json")
    semaphore = asyncio.Semaphore(args.concurrency)
    stop = asyncio.Event()
    consecutive_errors = 0
    client = genai.Client(api_key=api_key(), http_options=types.HttpOptions(
        timeout=config["http_timeout_ms"], retry_options=types.HttpRetryOptions(attempts=1)))
    generation = types.GenerateContentConfig(
        response_mime_type="application/json", response_json_schema=schema,
        temperature=config["temperature"], seed=config["seed"],
        max_output_tokens=config["max_output_tokens"],
        thinking_config=types.ThinkingConfig(thinking_budget=0))

    async def one(row):
        nonlocal consecutive_errors
        async with semaphore:
            identifier = sample_id(row)
            target = rawdir / f"{identifier}.json"
            if target.exists() or identifier in ledger.data["entries"] or stop.is_set():
                return
            result = {"sample_id": identifier, "split": row["split"], "started_at": utc_now(),
                      "selection_manifest_sha256": frozen["manifest_sha256"],
                      "request_config_sha256": frozen["request_config_sha256"], "status": "not_attempted"}
            path = image_path(row)
            downloaded = downloads.get(identifier, {})
            if downloaded.get("download_status") != "ok" or not path.is_file():
                # Can resume when downloads finish: don't create a terminal record.
                print(json.dumps({"sample_id": identifier, "status": "image_pending"}), flush=True)
                return
            binary = path.read_bytes()
            digest = sha256(binary)
            expected = downloaded.get("image_sha256")
            if downloaded.get("image_path") != row["image_path"] or not expected or digest != expected:
                raise RuntimeError("Image checksum mismatch")
            result["image_sha256"] = digest
            request_digest = sha256(canonical({"config": frozen["request_config_sha256"], "image": digest}))
            result["request_sha256"] = request_digest
            contents = [prompt, types.Part.from_bytes(data=binary, mime_type=mimetypes.guess_type(path.name)[0] or "image/png")]
            try:
                count = await client.aio.models.count_tokens(model=config["model"], contents=contents)
                # The count API does not accept generation_config on Developer API.
                # UTF-8 schema bytes + 4096 are a deliberately loose extra bound.
                upper = int(count.total_tokens) + len(canonical(schema)) + config["schema_extra_margin_tokens"]
                result.update(counted_input_tokens=count.total_tokens, input_upper_bound_tokens=upper)
                if upper > config["max_counted_input_plus_schema_margin"]:
                    result["status"] = "input_token_bound_exceeded"
                    atomic_json(target, result)
                    stop.set()
                    return
            except Exception as exc:
                result.update(status="count_tokens_failed", error_type=type(exc).__name__)
                atomic_json(target, result)
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    stop.set()
                print(json.dumps({"sample_id": identifier, "status": result["status"], "error_type": result["error_type"]}), flush=True)
                return
            if stop.is_set():
                return
            try:
                ledger.reserve(identifier, request_digest)
            except BudgetError:
                stop.set()
                print(json.dumps({"status": "budget_stop", **ledger.summary()}), flush=True)
                return
            started = time.perf_counter()
            usage = None
            try:
                response = await client.aio.models.generate_content(model=config["model"], contents=contents, config=generation)
                usage = response.usage_metadata.model_dump(mode="json") if response.usage_metadata else None
                text = response.text or ""
                finish = str(response.candidates[0].finish_reason) if response.candidates else None
                result.update(status="response_received", raw_text=text, usage=usage, finish_reason=finish,
                              model_version=response.model_version)
                try:
                    parsed = json.loads(text)
                    result["json_object_valid"] = isinstance(parsed, dict)
                except (ValueError, TypeError):
                    result["json_object_valid"] = False
                consecutive_errors = 0
                if usage and ((usage.get("prompt_token_count") or 0) > config["max_counted_input_plus_schema_margin"]
                              or (usage.get("candidates_token_count") or 0) + (usage.get("thoughts_token_count") or 0) > config["max_output_tokens"]):
                    result["token_bound_violation"] = True
                    stop.set()
            except Exception as exc:
                # Do not print provider exception strings: some include request URLs.
                result.update(status="generation_failed", error_type=type(exc).__name__,
                              error_code=getattr(exc, "code", None))
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    stop.set()
            finally:
                result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                result["completed_at"] = utc_now()
                # Save response first. A crash before settlement leaves $.50 reserved.
                atomic_json(target, result)
                ledger.settle(identifier, usage, result["status"])
                atomic_json(EVAL / "cost_summary.json", ledger.summary())
            print(json.dumps({"sample_id": identifier, "status": result["status"],
                              "json_valid": result.get("json_object_valid"), "latency_ms": result["latency_ms"],
                              **ledger.summary()}), flush=True)

    try:
        await asyncio.gather(*(one(row) for row in selected))
    finally:
        await client.aio.aclose()
        client.close()
        atomic_json(EVAL / "cost_summary.json", ledger.summary())
    print(json.dumps({"split": args.split, "selected": len(selected), "stopped": stop.is_set(), **ledger.summary()}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/nutrition5k/selection_manifest.jsonl")
    parser.add_argument("--download-manifest", type=Path, default=ROOT / "data/nutrition5k/manifest.jsonl")
    parser.add_argument("--freeze", type=Path, default=EVAL / "manifest_freeze.json")
    parser.add_argument("--split", choices=["pilot", "blind_test"], required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 4:
        parser.error("Concurrency must be between 1 and 4")
    with process_lock(EVAL / "tmp/collector.lock"):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
