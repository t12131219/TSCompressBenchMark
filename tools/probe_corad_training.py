#!/usr/bin/env python3
"""Run the exact shipped CORAD Python bridge after the local source build audit."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import check_sources  # noqa: E402
from tsbench.assets import digest, load_json, require, verify_asset  # noqa: E402
from tsbench.build.environment import check_tsbench  # noqa: E402


def check_training_environment():
    prefix = Path(sys.prefix).resolve()
    check_tsbench(ROOT)
    import numpy as np
    import pandas
    import scipy
    import sklearn
    packages = (np, pandas, scipy, sklearn)
    for mod, expected in zip(packages, ("1.24.3", "2.0.3", "1.11.1", "1.3.0")):
        require(mod.__version__ == expected and Path(mod.__file__).resolve().is_relative_to(prefix),
                f"unexpected module version or prefix: {mod.__name__}")
    require(sys.version_info[:3] == (3, 11, 5), "unexpected Python version")
    return {p.__name__: p.__version__ for p in packages}


def main(out: Path):
    versions = check_training_environment()
    import numpy as np
    source = check_sources(ROOT)["sources"]["corad-native"]
    published = load_json(verify_asset(ROOT, source["source_manifest"]))
    relative = "corad-native/source_backend/train.py"
    builds = out / "release-builds"
    extracted = builds / "corad-native/source"
    bridge = extracted / relative
    require(digest(bridge) == {row["path"]: row["sha256"] for row in published["files"]}[relative], "source training bridge identity mismatch")
    audit = out / "corad-source-training"
    audit.mkdir()
    sample, model = audit / "input.npy", audit / "model.json"
    # Miniature analytic data. This is an execution/import check, not oracle or quality evidence.
    rows = np.indices((24, 4), dtype=np.int64)
    np.save(sample, ((rows[0] * 7 + rows[1] * 13) % 19 - 9).astype(np.float64) / 4)
    cmd = [sys.executable, "-I", "-B", str(bridge), "--input", str(sample), "--output", str(model),
           "--atoms", "3", "--alpha", "0.25", "--source-root", str(extracted / "corad-native")]
    env = {**os.environ, **{k: "1" for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}}
    result = subprocess.run(cmd, env=env, capture_output=True, timeout=30, check=False)
    (audit / "stdout.log").write_bytes(result.stdout)
    (audit / "stderr.log").write_bytes(result.stderr)
    result.check_returncode()
    data = load_json(model)
    require(data["backend"] == "upstream-CORAD-sklearn-DictionaryLearning" and
            data["rows"] == 24 and data["features"] == 4 and data["max_iter"] == 10 and data["alpha"] == 0.25 and
            np.asarray(data["dictionary"]).shape == (3, 4) and np.isfinite(data["dictionary"]).all(),
            "invalid reference bridge output")
    summary = {"schema": "bmk.corad-source-training-probe/1", "qualification_granted": False,
               "argv": cmd, "returncode": result.returncode, "python": sys.version,
               "versions": versions,
               "environment_lock_sha256": digest(ROOT / "environment/tsbench-linux-64.lock.json"),
               "bridge_sha256": digest(bridge), "model_sha256": digest(model), "input_sha256": digest(sample),
               "network_namespace": os.readlink("/proc/self/ns/net"),
               "source_root_semantics": "required CLI value; frozen bridge does not read any files from it",
               "scope": "executability and finite model shape only; solver defaults and RNG unchanged"}
    (audit / "audit.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
