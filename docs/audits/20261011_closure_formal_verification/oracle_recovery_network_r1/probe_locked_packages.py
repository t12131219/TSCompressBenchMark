"""Probe exact legacy packages via official metadata/HEAD and bounded small GETs.

Never installs or imports acquired code. Writes only a new audit directory;
large CUDA/TensorFlow/NumPy packages remain metadata-only.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
MAX_METADATA = 2_000_000
MAX_SMALL_PACKAGE = 1_000_000
MAX_TOTAL_SMALL_PACKAGES = 5_000_000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text())


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("preserve existing artifact: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(data)


def path_ref(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(data), "bytes": len(data)}


def request(url, method="GET", cap=MAX_METADATA):
    host = urllib.parse.urlsplit(url).hostname
    if host not in {"pypi.org", "files.pythonhosted.org", "repo.anaconda.com", "api.anaconda.org"}:
        raise ValueError("only exact official metadata/artifact URLs may be requested")
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "TSBench-Legacy-Lock-Audit/1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = b"" if method == "HEAD" else response.read(cap + 1)
            if len(data) > cap:
                raise ValueError("response exceeds predeclared small payload limit")
            final = urllib.parse.urlsplit(response.url)
            result = {"url": url, "method": method, "status": response.status,
                      "final_host": final.hostname, "final_path": final.path,
                      "content_length": response.headers.get("Content-Length"),
                      "content_type": response.headers.get("Content-Type"),
                      "etag": response.headers.get("ETag"), "bytes_read": len(data),
                      "redirect_query_saved": False, "success": True}
            return result, data
    except Exception as error:
        return {"url": url, "method": method, "success": False,
                "error_type": type(error).__name__, "error": str(error)}, None


def package_name_version(filename):
    if filename.endswith(".whl"):
        return tuple(filename.split("-")[:2])
    for suffix in (".tar.gz", ".zip", ".tar.bz2"):
        if filename.endswith(suffix):
            return tuple(filename.removesuffix(suffix).rsplit("-", 1))
    raise ValueError("unsupported locked filename")


def build_inventory():
    base = read("Source__deepzip__ORACLE_ENVIRONMENT_LOCK.json")
    cpu = read("Source__dzip__ORACLE_ENVIRONMENT_LOCK.json")
    gpu = read("Source__dzip__GPU_ORACLE_ENVIRONMENT_LOCK.json")
    items = []
    for kind in ("conda", "pip_acquisition_archives"):
        for item in base[kind]:
            items.append({"recipe": "deepzip_base", "kind": "conda" if kind == "conda" else "pip",
                          "filename": item["filename"], "sha256": item["sha256"],
                          "bytes": item["size_bytes"], "locked_url": item.get("url")})
    for item in cpu["overlay_archives"]:
        items.append({"recipe": "dzip_cpu_overlay", "kind": "pip", "filename": item["filename"],
                      "sha256": item["sha256"], "bytes": item["bytes"], "locked_url": None})
    for item in gpu["packages"]:
        items.append({"recipe": "dzip_gpu_overlay", "kind": "conda" if item["name"].endswith(".conda") else "pip",
                      "filename": item["name"], "sha256": item["sha256"], "bytes": None,
                      "locked_url": item.get("url")})
    unique = {}
    for item in items:
        key = item["sha256"]
        if key not in unique:
            unique[key] = {**item, "recipes": [item["recipe"]]}
        else:
            unique[key]["recipes"].append(item["recipe"])
            if unique[key]["bytes"] is None:
                unique[key]["bytes"] = item["bytes"]
    old_local = json.loads((ROOT / "docs/audits/20261011_closure_formal_verification/gate_audit/environment_inventory.json").read_text())
    for item in unique.values():
        old = next((row for row in old_local["acquisition_archives"] if row["sha256"] == item["sha256"]), None)
        item["previous_local_matches"] = [] if old is None else old["matching_local_bytes"]
        if item["kind"] == "pip":
            item["project"], item["version"] = package_name_version(item["filename"])
    return items, list(unique.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small-downloads", action="store_true")
    args = parser.parse_args()
    refs, items = build_inventory()
    metadata_tasks = {}
    for item in items:
        if item["kind"] == "pip":
            key = item["project"], item["version"]
            metadata_tasks[key] = "https://pypi.org/pypi/" + "/".join(urllib.parse.quote(part, safe="") for part in key) + "/json"
    metadata = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(request, url): key for key, url in metadata_tasks.items()}
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            result, payload = future.result()
            if payload is not None:
                name = re.sub(r"[^A-Za-z0-9._-]", "_", "-".join(key)) + ".json"
                path = OUT / "metadata" / name
                save(path, payload)
                result["saved_metadata"] = path_ref(path)
                metadata[key] = result, json.loads(payload)
            else:
                metadata[key] = result, None
        conda = [item for item in items if item["kind"] == "conda"]
        futures = {pool.submit(request, item["locked_url"], "HEAD"): item for item in conda}
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            result, _ = future.result()
            item["remote_probe"] = result
            length = result.get("content_length")
            if item["bytes"] is None and length and length.isdigit():
                item["bytes"] = int(length)
                item["size_source"] = "OFFICIAL_HEAD_CONTENT_LENGTH_NOT_ORIGINAL_LOCK"
            item["resolved_url"] = item["locked_url"] if result["success"] else None
            item["remote_availability"] = "HEAD_ACCESSIBLE_HASH_NOT_YET_VERIFIED" if result["success"] else "NETWORK_PROBE_FAILED"
    for item in items:
        if item["kind"] != "pip":
            continue
        result, document = metadata[item["project"], item["version"]]
        candidates = [] if document is None else [entry for entry in document["urls"]
                       if entry["filename"] == item["filename"] and entry["digests"]["sha256"] == item["sha256"]]
        item["remote_probe"] = result
        if len(candidates) == 1:
            entry = candidates[0]
            item["resolved_url"] = entry["url"]
            item["pypi_published_size"] = entry["size"]
            item["pypi_yanked"] = entry.get("yanked")
            item["pypi_requires_python"] = entry.get("requires_python")
            if item["bytes"] is None:
                item["bytes"] = entry["size"]
                item["size_source"] = "OFFICIAL_PYPI_METADATA_NOT_ORIGINAL_LOCK"
            item["remote_availability"] = "OFFICIAL_FILENAME_SHA_SIZE_MATCH" if item["bytes"] == entry["size"] else "REMOTE_SIZE_MISMATCH"
        else:
            item["resolved_url"] = None
            item["remote_availability"] = "EXACT_LOCKED_FILE_NOT_IN_OFFICIAL_VERSION_METADATA" if document else "NETWORK_PROBE_FAILED"
    total = 0
    downloads = []
    if args.small_downloads:
        priority = {"Keras-2.2.2-py2.py3-none-any.whl", "Keras_Applications-1.0.4-py2.py3-none-any.whl",
                    "Keras_Preprocessing-1.0.2-py2.py3-none-any.whl", "gast-0.2.2.tar.gz"}
        for item in sorted(items, key=lambda item: (item["filename"] not in priority, item["bytes"] or 10**15, item["filename"])):
            n = item["bytes"]
            if not item["resolved_url"] or not n or n > MAX_SMALL_PACKAGE or total + n > MAX_TOTAL_SMALL_PACKAGES or item["previous_local_matches"]:
                continue
            result, payload = request(item["resolved_url"], cap=MAX_SMALL_PACKAGE)
            item["small_download_probe"] = result
            if payload is None:
                continue
            total += len(payload)
            result["actual_sha256"] = sha(payload)
            result["exact_lock_bytes_verified"] = len(payload) == n and sha(payload) == item["sha256"]
            path = OUT / "small_payloads" / item["filename"]
            save(path, payload)
            result["artifact"] = path_ref(path)
            downloads.append(result)
    gpu_path = ROOT / "docs/audits/20261011_closure_formal_verification/gpu_access_supplement.json"
    result = {"schema_version": "tscb.legacy-oracle-network-recovery-feasibility.v1",
              "created_at": datetime.now(UTC).isoformat(), "execution_context": "SANDBOX_EXTERNAL_READ_ONLY_NETWORK_PROBE",
              "driver": path_ref(Path(__file__)), "gpu_supplement": path_ref(gpu_path),
              "historical_archive": path_ref(ROOT / "docs/rewrite_cleanup/20261006-integration/historical_metadata.tar.gz"),
              "lock_references": [path_ref(path) for path in sorted(OUT.glob("Source__*LOCK.json"))],
              "acquisition_reference_count": len(refs), "unique_archive_count": len(items),
              "package_type_counts": dict(Counter(item["kind"] for item in items)),
              "resolved_unique_archive_bytes": sum(item["bytes"] or 0 for item in items),
              "network_status_counts": dict(Counter(item["remote_availability"] for item in items)),
              "small_download_file_count": len(downloads), "small_download_bytes": total,
              "per_package_download_cap": MAX_SMALL_PACKAGE, "total_package_download_cap": MAX_TOTAL_SMALL_PACKAGES,
              "reference_groups": refs, "archives": items,
              "packages_installed": False, "environment_created": False,
              "oracle_codec_training_or_performance_executed": False, "G1_G5_CAP_FULL_PARITY_granted": False,
              "claim_boundary": "Public metadata and bounded exact acquisition evidence only. Access is not runtime compatibility or oracle parity. Large packages have not been downloaded or hashed here."}
    save(OUT / "network_recovery_report.json", json.dumps(result, ensure_ascii=False, indent=2).encode() + b"\n")
    print(json.dumps({key: result[key] for key in ("acquisition_reference_count", "unique_archive_count", "resolved_unique_archive_bytes", "network_status_counts", "small_download_file_count", "small_download_bytes")}), flush=True)


if __name__ == "__main__":
    main()
