"""Inspect restored code/ELF bytes against archived installed hashes and exact wheels.

No environment package, source oracle or codec is imported or executed.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parent
BUILD = ROOT / "build/legacy-oracle-recovery-20261011/oracle-recovery-r1"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path):
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def installed_base_audit():
    lock_path = AUDIT / "Source__deepzip__ORACLE_ENVIRONMENT_LOCK.json"
    lock = json.loads(lock_path.read_text())
    prefix = BUILD / "deepzip-tf18"
    site = prefix / "lib/python3.6/site-packages"
    rows = []
    for distribution in lock["distributions"]:
        for item in distribution["files"]:
            path = (site / item["path"]).resolve()
            metadata = ".dist-info/" in item["path"] or ".egg-info/" in item["path"]
            script = item["path"].startswith("../")
            category = "RELOCATION_SCRIPT" if script else "INSTALL_METADATA" if metadata else "LOCKED_PACKAGE_CODE_OR_DATA"
            actual = sha(path) if path.is_file() else None
            rows.append({"distribution": distribution["name"], "version": distribution["version"],
                         "relative_path": item["path"], "actual_path": str(path), "category": category,
                         "expected_sha256": item["sha256"], "actual_sha256": actual,
                         "status": "MATCH" if actual == item["sha256"] else "MISSING" if actual is None else "HASH_DIFFERENCE"})
    core = [row for row in rows if row["category"] == "LOCKED_PACKAGE_CODE_OR_DATA"]
    conda_rows = []
    for expected in lock["conda"]:
        meta = prefix / "conda-meta" / (expected["name"] + "-" + expected["version"] + "-" + expected["build"] + ".json")
        actual = json.loads(meta.read_text()) if meta.exists() else {}
        conda_rows.append({"name": expected["name"], "expected_version": expected["version"], "expected_build": expected["build"],
                           "actual_version": actual.get("version"), "actual_build": actual.get("build"),
                           "status": "VERSION_BUILD_MATCH" if actual.get("version") == expected["version"] and actual.get("build") == expected["build"] else "MISSING_OR_MISMATCH",
                           "metadata": ref(meta) if meta.exists() else None})
    return {"original_lock": ref(lock_path), "prefix": str(prefix), "recorded_file_count": len(rows),
            "recorded_distribution_count": len(lock["distributions"]),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "code_or_data_status_counts": dict(Counter(row["status"] for row in core)),
            "all_recorded_code_or_data_matches": all(row["status"] == "MATCH" for row in core),
            "relocation_and_install_metadata_differences": [row for row in rows if row["status"] != "MATCH" and row["category"] != "LOCKED_PACKAGE_CODE_OR_DATA"],
            "all_file_results": rows, "conda_packages": conda_rows,
            "empty_original_file_inventory_distributions": [distribution["name"] for distribution in lock["distributions"] if not distribution["files"]]}


def overlay_wheel_audit(key, filenames):
    site = BUILD / key / "lib/python3.6/site-packages"
    base_site = BUILD / "deepzip-tf18/lib/python3.6/site-packages"
    rows, sdist = [], []
    for filename in filenames:
        path = BUILD / "downloads/pip" / filename
        if not filename.endswith(".whl"):
            sdist.append({"filename": filename, "archive": ref(path), "limitation": "Original exact sdist installed; no historical generated installed-file lock for this overlay. Acquisition SHA alone is not a full installed-code equivalence proof."})
            continue
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.endswith((".py", ".so")) or ".dist-info/" in info.filename:
                    continue
                target = site / info.filename
                inherited = False
                if not target.exists():
                    target = base_site / info.filename
                    inherited = True
                h = hashlib.sha256()
                with archive.open(info) as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(block)
                expected = h.hexdigest()
                actual = sha(target) if target.is_file() else None
                rows.append({"filename": filename, "member": info.filename, "expected_sha256": expected,
                             "actual_sha256": actual, "actual_path": str(target), "inherited_base": inherited,
                             "status": "MATCH" if actual == expected else "MISSING" if actual is None else "HASH_DIFFERENCE"})
        print(json.dumps({"stage": "overlay_installed_bytes", "environment": key, "archive": filename}), flush=True)
    return {"environment": key, "selected_archive_count": len(filenames), "checked_py_or_so_members": len(rows),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "all_checked_py_or_so_matches": all(row["status"] == "MATCH" for row in rows),
            "rows": rows, "sdist_limits": sdist}


def main():
    output = BUILD / "installed_byte_audit.json"
    if output.exists():
        raise FileExistsError("preserve earlier installed byte audit")
    base = installed_base_audit()
    cpu = json.loads((AUDIT / "Source__dzip__ORACLE_ENVIRONMENT_LOCK.json").read_text())
    gpu = json.loads((AUDIT / "Source__dzip__GPU_ORACLE_ENVIRONMENT_LOCK.json").read_text())
    overlays = [overlay_wheel_audit("dzip-tf114-cpu", [item["filename"] for item in cpu["overlay_archives"]]),
                overlay_wheel_audit("dzip-tf114-gpu", [item["name"] for item in gpu["packages"] if not item["name"].endswith(".conda")])]
    document = {"schema_version": "tscb.exact-restored-package-byte-audit.v1", "driver": ref(Path(__file__)),
                "deepzip_original_installed_hash_audit": base, "overlay_wheel_code_audits": overlays,
                "source_oracle_codec_training_or_performance_executed": False,
                "all_gates_or_full_parity_granted": False,
                "claim_boundary": "Recorded package byte and actual source/ELF integrity only. Metadata/relocation differences are retained; overlays without installed source locks remain explicitly limited."}
    with output.open("x") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"base": base["status_counts"], "base_code_or_data": base["code_or_data_status_counts"],
                      "overlays": [{"environment": row["environment"], "counts": row["status_counts"]} for row in overlays]}))


if __name__ == "__main__":
    main()
