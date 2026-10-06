"""Check retained identities and fresh native builds after source-only cleanup."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "Compression_Rewrite"
AUDIT = PROJECT / "docs/rewrite_cleanup/20261006-integration"
TORCH = Path("/home/fzg/anaconda3/envs/CompressBench/lib/python3.11/site-packages/torch")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    plan = json.loads((AUDIT / "cleanup_plan.json").read_text())
    result = json.loads((AUDIT / "cleanup_result.json").read_text())
    changes = {
        "ReWrite/prometheus-histogram-st/CMakeLists.txt",
        "ReWrite/dzip/CMakeLists.txt",
        "ReWrite/walloc-1d/MODEL_MANIFEST.json",
        "ReWrite/walloc-1d/README.md",
    }
    for relative, info in plan["keep"].items():
        path = ROOT / relative
        assert path.exists(), relative
        if info["sha256"] and relative not in changes:
            assert sha(path) == info["sha256"], relative
    for item in result["assets"]:
        assert sha(ROOT / item["destination"]) == item["sha256"]
    cmakes = sorted((ROOT / "ReWrite").glob("*/CMakeLists.txt"))
    assert len(cmakes) == 14
    builds = Path(tempfile.mkdtemp(prefix="rewrite-integration-check-"))
    (AUDIT / "temporary_build_root.json").write_text(json.dumps({"path": str(builds)}) + "\n")

    def check(source):
        name = source.parent.name
        out = builds / name
        flags = ["-DCMAKE_BUILD_TYPE=Release"]
        if name in {"tristan", "corad"}:
            flags += ["-DTRISTAN_MKL_ROOT=/home/fzg/anaconda3"]
        if name == "deepzip":
            flags += ["-DDEEPZIP_WITH_HDF5=OFF", "-DDEEPZIP_WITH_CUDA=OFF"]
        if name == "dzip":
            flags += ["-DDZIP_WITH_HDF5=OFF", "-DDZIP_WITH_CUDA=OFF"]
        if name == "walloc-1d":
            flags += [
                f"-DWALLOC_TORCH_ROOT={TORCH}",
                "-DCMAKE_CUDA_COMPILER=/usr/local/cuda-11.8/bin/nvcc",
                "-DCUDAToolkit_ROOT=/usr/local/cuda-11.8",
            ]
        commands = [["cmake", "-S", str(source.parent), "-B", str(out), *flags]]
        if name != "walloc-1d":
            commands += [
                ["cmake", "--build", str(out), "-j2"],
                ["ctest", "--test-dir", str(out), "--output-on-failure"],
            ]
        actions = []
        for command in commands:
            run = subprocess.run(
                command,
                cwd=PROJECT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=360,
            )
            actions.append(dict(command=command, returncode=run.returncode, output=run.stdout))
            (AUDIT / (name + "-build.log")).write_text("\n".join(a["output"] for a in actions))
            if run.returncode:
                break
        passed = all(a["returncode"] == 0 for a in actions) and len(actions) == len(commands)
        print(
            json.dumps(
                dict(
                    algorithm=name,
                    status="PASS" if passed else "FAIL",
                    scope="configure only" if name == "walloc-1d" else "CPU build and ctest",
                )
            ),
            flush=True,
        )
        return dict(
            algorithm=name,
            status="PASS" if passed else "FAIL",
            actions=actions,
            scope="configure only" if name == "walloc-1d" else "CPU build and ctest",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(check, cmakes))
    report = dict(
        status="PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
        retained_source_and_asset_hashes_verified=True,
        permitted_metadata_changes=sorted(changes),
        builds=checks,
        scope="Source cleanup regression, not renewed FULL_PARITY or benchmark qualification.",
        limitations=[
            "CUDA/HDF5 variants not rebuilt; "
            "WaLLoC configured only against installed native dependencies.",
            "FlexTEC has no canonical C++ and remains blocked; "
            "reference core and provenance retained.",
        ],
        temporary_build_root=str(builds),
    )
    (AUDIT / "build_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    assert builds.parent == Path(tempfile.gettempdir()) and builds.name.startswith(
        "rewrite-integration-check-"
    )
    if report["status"] == "PASS":
        shutil.rmtree(builds)
        print("PASS: temporary verification build artifacts removed", flush=True)
    else:
        raise RuntimeError(
            "Retained build failure; inspect saved logs and preserve temporary checkout"
        )


if __name__ == "__main__":
    main()
