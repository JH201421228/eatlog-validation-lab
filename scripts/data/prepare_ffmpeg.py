"""Prepare a pinned local ffmpeg executable without installing a Python package.

Windows x64 helper. Other platforms may supply an existing ffmpeg executable
to collect_nutrition5k.py --ffmpeg; record its version/hash in study provenance.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from collect_nutrition5k import ROOT, SOURCE, dump_json, fetch, utc_now

VERSION = "0.6.0"
FILENAME = "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl"
WHEEL_SHA256 = "02fa47c83703c37df6bfe4896aab339013f62bf02c5ebf2dce6da56af04ffc0a"
EXE_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
EXE_MEMBER = "imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"


def main():
    directory = ROOT / "data" / "downloads" / "tools"
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / FILENAME
    api_url = f"https://pypi.org/pypi/imageio-ffmpeg/{VERSION}/json"
    metadata = json.loads(fetch(api_url))
    artifact = next(row for row in metadata["urls"] if row["filename"] == FILENAME)
    if artifact["digests"]["sha256"] != WHEEL_SHA256:
        raise ValueError("Pinned wheel differs from PyPI digest")
    if not wheel.exists():
        wheel.write_bytes(fetch(artifact["url"]))
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
        raise ValueError("Downloaded wheel SHA256 differs from pinned artifact")
    executable = directory / "ffmpeg.exe"
    with zipfile.ZipFile(wheel) as archive:
        binary = archive.read(EXE_MEMBER)
        if hashlib.sha256(binary).hexdigest() != EXE_SHA256:
            raise ValueError("Unexpected executable SHA256")
        if executable.exists():
            if hashlib.sha256(executable.read_bytes()).hexdigest() != EXE_SHA256:
                raise ValueError("Existing executable differs from pinned artifact")
        else:
            executable.write_bytes(binary)
        license_member = "imageio_ffmpeg-0.6.0.dist-info/LICENSE"
        (SOURCE / license_member.replace("/", "_")).write_bytes(archive.read(license_member))
    version = subprocess.run([str(executable), "-version"], capture_output=True, text=True, check=True).stdout
    license_result = subprocess.run([str(executable), "-hide_banner", "-L"], capture_output=True, text=True, check=True)
    (SOURCE / "ffmpeg_license.txt").write_text(license_result.stdout + license_result.stderr, encoding="utf-8")
    provenance = {"package": "imageio-ffmpeg", "version": VERSION, "wheel_file": FILENAME,
        "wheel_url": artifact["url"], "pypi_metadata_url": api_url, "verified_at_utc": utc_now(),
        "wheel_sha256": WHEEL_SHA256, "exe_sha256": EXE_SHA256, "exe_version": version,
        "tool_purpose": "Extract unchanged first decoded frame (index 0) from the officially resolved camera h264 file; no environment install",
        "binary_redistributed_in_git": False}
    dump_json(SOURCE / "ffmpeg_provenance.json", provenance)
    print(json.dumps({"executable": executable.relative_to(ROOT).as_posix(), "exe_sha256": EXE_SHA256}))


if __name__ == "__main__":
    main()
