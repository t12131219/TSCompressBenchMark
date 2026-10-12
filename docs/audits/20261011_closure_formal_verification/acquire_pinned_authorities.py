"""Acquire exact missing public source commits into a new audit-only directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUTHORITIES = {
    "elf": (
        "https://github.com/Spatio-Temporal-Lab/elf.git",
        "386d69348e6c30475761d3519ee0bfe10ed473d3",
    ),
    "dipperstein-lzss": (
        "https://github.com/MichaelDipperstein/lzss.git",
        "65b6882ff1cc225f9c6fcd947def7b1adb21d578",
    ),
    "dipperstein-bitfile": (
        "https://github.com/MichaelDipperstein/bitfile.git",
        "2e6132f75cbe16842a9ab81af7756ed9ac1cdbe0",
    ),
    "dipperstein-optlist": (
        "https://github.com/MichaelDipperstein/optlist.git",
        "c921d0f8f7b2fc3d454ba897a3bf04beecb6899a",
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=AUTHORITIES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT):
        parser.error("choose a new project output; preserve previous attempts")
    output.mkdir(parents=True)
    repo = output / "repository.git"
    url, commit = AUTHORITIES[args.name]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    commands = [
        ["git", "init", "--bare", str(repo)],
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "core.hooksPath=/dev/null",
            "fetch",
            "--depth=1",
            "--no-tags",
            url,
            commit,
        ],
    ]
    attempts = []
    for index, command in enumerate(commands):
        log = output / f"command-{index}.log"
        with log.open("xb") as handle:
            try:
                result = subprocess.run(
                    command, env=env, stdout=handle, stderr=subprocess.STDOUT, timeout=120
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
        attempts.append(
            {
                "command": command,
                "exit_code": code,
                "log": str(log.relative_to(ROOT)),
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }
        )
        if code:
            break
    document = {
        "name": args.name,
        "url": url,
        "commit": commit,
        "attempts": attempts,
        "status": "ACQUIRED_NOT_YET_VERIFIED" if code == 0 else "NOT_ACQUIRED",
        "source_lock_changed": False,
        "codec_executed": False,
    }
    (output / "acquisition.json").write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps(document), flush=True)
    raise SystemExit(0 if code == 0 else 1)


if __name__ == "__main__":
    main()
