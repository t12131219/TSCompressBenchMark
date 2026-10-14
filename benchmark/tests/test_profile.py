from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from tsbench.config import resolve
from tsbench.profile import run_profile, snapshot
from tsbench.runner import run


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="procfs resource sampler is Linux-specific")
def test_resource_sampler_includes_real_descendant_process():
    child = subprocess.Popen([sys.executable, "-c",
                              "import sys; memory=bytearray(8*1024*1024); print('ready',flush=True); sys.stdin.readline()"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        sample = snapshot(os.getpid())
        assert sample["available"]
        process = next(p for p in sample["processes"] if p["pid"] == child.pid)
        assert process["rss_bytes"] >= 8 * 1024**2
        assert sample["rss_bytes"] >= process["rss_bytes"]
    finally:
        child.communicate("done\n", timeout=10)


def test_profile_replays_raw_run_into_independent_pass(tmp_path):
    np.save(tmp_path / "source.npy", np.arange(17, dtype=np.float64))
    config = resolve({"schema": "tsbench.experiment/1", "name": "profile-contract",
                      "output": str(tmp_path / "primary"), "build_root": str(tmp_path / "build"),
                      "datasets": [{"id": "values", "path": "source.npy", "format": "npy"}],
                      "methods": [{"id": "raw", "codec": "raw-store"}],
                      "execution": {"rounds": 1, "warmup_objects": 0, "timeout_s": 30}}, tmp_path)
    primary = run(config)
    observations = primary / "observations.jsonl"
    original = observations.read_bytes()
    primary_manifest = (primary / "manifest.json").read_bytes()
    profiled = run_profile(primary / "manifest.json", interval_ms=10)
    assert profiled.parent == primary / "profile"
    assert observations.read_bytes() == original
    assert (primary / "manifest.json").read_bytes() == primary_manifest
    profile_manifest = json.loads((profiled / "manifest.json").read_text())
    assert profile_manifest["pass_kind"] == "profile"
    resources = json.loads((profiled / "resources.json").read_text())
    assert resources["source_run_id"] == json.loads(primary_manifest)["run_id"]
    assert resources["pass_kind"] == "profile" and resources["sample_count"] > 1
    assert resources["per_trial_peak"] is None
    assert resources["peak_interpretation"].startswith("sampled lower bound")
    assert (profiled / "resource_samples.jsonl").is_file()
