"""Shared test-only invocation for the relocated native worker lanes."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def run_worker(root, argv, *, check=True, library_dir=None):
    env = {"LC_ALL": "C", "HOME": str(root)}
    if library_dir is not None:
        env["LD_LIBRARY_PATH"] = str(library_dir)
    result = subprocess.run(argv, cwd=root, env=env,
                            capture_output=True, timeout=15)
    if check and result.returncode != 0:
        raise AssertionError(f"{argv}: {result.returncode}: {result.stderr.decode(errors='replace')}")
    return result
