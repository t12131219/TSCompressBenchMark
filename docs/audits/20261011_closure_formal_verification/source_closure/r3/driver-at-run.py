"""Read-only independent source inventory; never builds or imports codec code.

Expectations come from existing registered locks or pinned Git objects. A new
observation of the installed tree is never promoted into an upstream expectation.
Git tree availability, selected vendor provenance, and semantic parity are separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[4]
AUTHORITY_BASE = Path("/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos")
REPOSITORIES = {
    "inikep_lzbench": "fa871e66b3543a70fd4d060f7c12719343ff4ac3",
    "cwida_ALP": "31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce",
    "Cyan4973_FiniteStateEntropy": "9f30e0918f87bd835fa040d922a208d7b219e50b",
    "sprintz-lzbench": "580c4f085381f31b1ad669525ed04e63cbc385f3",
    "dblalock_sprintz": "a056cdb67d049669875ab5487359aca99ae873ea",
    "lemire_simdcomp": "d5301778fe5045ca8099252de5a6ed8016a287df",
    "mohit1997_DeepZip": "8c35502397a1488c89fa282ed033cc9d5fd4b4dc",
    "mohit1997_DZip": "b52ed99687919a744dfdc3dc7a968b2331ee7102",
    "nla-group_ABBA": "614d56841cd2f1c2925cea4d2c2648a7b2ac791d",
    "nla-group_fABBA": "4066a5fc778f50f4bee1c41d8f3ab3ee4a3ff6ad",
    "panagiotisl_chimp": "320d397157c7e0696b3c64dc1711fc17a3add3da",
    "Spatio-Temporal-Lab_elf": "64e0d6004be322d9d8eaf9931e371df202f1a0eb",
    "Spatio-Temporal-Lab_SElfStar": "457ceb0033e98d516fef42e39d17c9d4b8abbfdb",
    "and-gue_NeaTS": "2d804ff492e45222e841dc1a50904476fa64f4a0",
    "Spatio-Temporal-Lab_Serf": "b38450b56825eabc96be8e25d6880127dc688c95",
    "LLNL_zfp": "c0c2c40b30d99f1787664b51c593fb6e0d729253",
    "alexkazik_lzss": "512b9163d8a936003c925e24f7f682eeaeda8307",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": digest(path.read_bytes())}


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *arguments],
                          check=True, capture_output=True,
                          env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}).stdout


def checked_git_tree(name: str, commit: str) -> dict:
    """Read every pinned blob and recompute its Git object ID plus SHA-256.

    The entire tracked root is checked, rather than the current vendor selection.
    Gitlinks are listed explicitly and cannot be treated as dependency closure.
    """
    repo = AUTHORITY_BASE / name
    if git(repo, "rev-parse", f"{commit}^{{commit}}").decode().strip() != commit:
        raise RuntimeError("pinned commit cannot be resolved: " + name)
    tree = git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    entries = []
    for raw in git(repo, "ls-tree", "-rz", commit).split(b"\0"):
        if raw:
            metadata, raw_path = raw.split(b"\t", 1)
            mode, kind, oid = metadata.decode().split()
            entries.append({"path": raw_path.decode(), "mode": mode, "kind": kind,
                            "git_object_id": oid})
    process = subprocess.Popen(["git", "--no-optional-locks", "-C", str(repo),
                                "cat-file", "--batch"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    byte_count = 0
    assert process.stdin is not None and process.stdout is not None
    try:
        for entry in entries:
            if entry["kind"] != "blob":
                continue
            process.stdin.write((entry["git_object_id"] + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().strip().split()
            if len(header) != 3 or header[1] != "blob":
                raise RuntimeError("missing or non-blob Git object: " + entry["path"])
            size = int(header[2])
            sha256 = hashlib.sha256()
            oid_hash = hashlib.sha1() if len(header[0]) == 40 else hashlib.sha256()
            oid_hash.update(f"blob {size}\0".encode())
            remaining = size
            while remaining:
                chunk = process.stdout.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise RuntimeError("truncated Git blob")
                sha256.update(chunk)
                oid_hash.update(chunk)
                remaining -= len(chunk)
            if process.stdout.read(1) != b"\n" or oid_hash.hexdigest() != entry["git_object_id"]:
                raise RuntimeError("Git object integrity mismatch: " + entry["path"])
            entry.update(bytes=size, sha256=sha256.hexdigest(), object_integrity="PASS")
            byte_count += size
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("Git batch reader failed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return {
        "repository_path": str(repo), "commit": commit, "root_tree_id": tree,
        "blob_integrity_status": "PASS_ALL_TRACKED_PINNED_BLOBS",
        "file_count": sum(x["kind"] == "blob" for x in entries), "bytes": byte_count,
        "gitlinks": [x for x in entries if x["kind"] == "commit"],
        "symlinks": [x["path"] for x in entries if x["mode"] == "120000"],
        "external_dependencies_complete": False, "source_semantic_parity_granted": False,
        "authority_kind": "EXISTING_LOCAL_PINNED_GIT_OBJECT_DATABASE_NO_NETWORK_AUTHENTICATION",
        "files": entries,
    }


def physical_inventory(root: Path) -> tuple[dict[str, str], list[str], list[str]]:
    files, excluded, links = {}, [], []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            links.append(relative)
        elif path.is_file():
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                excluded.append(relative)
            else:
                files[relative] = digest(path.read_bytes())
    return files, excluded, links


def verify_manifest(root: Path, expected: dict[str, str], *, exact: bool) -> dict:
    """Reject malformed paths, duplicates at caller, symlinks and all set drift."""
    malformed = [x for x in expected if PurePosixPath(x).is_absolute()
                 or ".." in PurePosixPath(x).parts or PurePosixPath(x).as_posix() != x]
    if malformed:
        return {"status": "FAIL_UNSAFE_PATH", "unsafe_paths": malformed}
    if exact:
        actual, excluded, links = physical_inventory(root)
    else:
        actual, excluded, links = {}, [], []
        for relative in expected:
            path = root / relative
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents
                                        if parent != root and parent.is_relative_to(root)):
                links.append(relative)
            elif path.is_file():
                actual[relative] = digest(path.read_bytes())
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected)) if exact else []
    mismatch = [x for x in sorted(set(expected) & set(actual)) if expected[x] != actual[x]]
    return {"status": "PASS" if not (missing or extra or mismatch or links) else "FAIL",
            "expected_count": len(expected), "observed_count": len(actual),
            "exact_set_required": exact, "missing": missing, "extra": extra,
            "hash_mismatch": mismatch, "symlinks_rejected": links,
            "cache_files_excluded": excluded,
            "expectation_source": "EXISTING_LOCK_OR_INDEPENDENT_PINNED_GIT_OBJECTS",
            "files": [{"path": x, "expected_sha256": expected[x],
                       "actual_sha256": actual.get(x)} for x in sorted(expected)]}


def mutation_tests() -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory(prefix="tscb-source-closure-negative-") as temporary:
        root = Path(temporary)
        expected = {"core.cc": digest(b"int source = 1;\n"), "api.h": digest(b"int source;\n")}
        for case in ("BASELINE", "BYTE_MUTATION", "MISSING_FILE", "EXTRA_FILE",
                     "PATH_ESCAPE", "SYMLINK"):
            for child in root.iterdir():
                child.unlink()
            (root / "core.cc").write_bytes(b"int source = 1;\n")
            (root / "api.h").write_bytes(b"int source;\n")
            expectation = dict(expected)
            if case == "BYTE_MUTATION":
                (root / "core.cc").write_bytes(b"int source = 2;\n")
            elif case == "MISSING_FILE":
                (root / "api.h").unlink()
            elif case == "EXTRA_FILE":
                (root / "hidden.cc").write_bytes(b"int extra;\n")
            elif case == "PATH_ESCAPE":
                expectation["../outside.cc"] = digest(b"outside")
            elif case == "SYMLINK":
                (root / "api.h").unlink()
                (root / "api.h").symlink_to(root / "core.cc")
            check = verify_manifest(root, expectation, exact=True)
            desired = check["status"] == "PASS" if case == "BASELINE" else check["status"].startswith("FAIL")
            results.append({"case": case, "expected_outcome": "ACCEPT" if case == "BASELINE" else "REJECT",
                            "status": "PASS" if desired else "FAIL", "verification": check})
    return results


def select(tree: dict, *, prefixes: tuple[str, ...] = (), names: tuple[str, ...] = (),
           excluded: tuple[str, ...] = ()) -> dict[str, str]:
    files = {x["path"]: x["sha256"] for x in tree["files"] if x["kind"] == "blob"}
    missing = set(names) - set(files)
    if missing:
        raise RuntimeError("authority is missing explicitly selected paths: " + str(sorted(missing)))
    return {p: sha for p, sha in files.items()
            if (p in names or p.startswith(prefixes)) and p not in excluded}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError("existing evidence must remain intact: " + str(output))
    output.mkdir(parents=True)
    old_path = ROOT / "docs/audits/20261011_porting_standard/source_build_inventory_r1/inventory-final-r2.json"
    old = json.loads(old_path.read_text())
    inputs = sorted((ROOT / "registry").rglob("*.json"))
    inputs += [old_path, ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json",
               ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json",
               ROOT / "adapters/simdcomp/SOURCE_LOCK.json", Path(__file__).resolve()]
    vendor_roots = {ROOT / tree["path"] for row in old["rows"]
                    for tree in row["source_inventory"]["observed_vendor_trees"]}
    inputs += sorted({file for tree in vendor_roots for file in tree.rglob("*")
                      if file.is_file() and "__pycache__" not in file.parts
                      and file.suffix not in {".pyc", ".pyo"}})
    before = [ref(x) for x in inputs]
    authorities = {}
    for name, commit in REPOSITORIES.items():
        print("Verifying all Git blobs: " + name, flush=True)
        authorities[name] = checked_git_tree(name, commit)
        write_new(output / "authorities" / (name + ".json"), authorities[name])
    source_documents = {digest(canonical(d["identity"])): (path, d)
                        for path in sorted((ROOT / "registry/sources").glob("*.artifact.json"))
                        for d in [json.loads(path.read_text())]}
    completed_lock = json.loads((ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json").read_text())
    api_lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
    simd_lock = json.loads((ROOT / "adapters/simdcomp/SOURCE_LOCK.json").read_text())
    selections = {
        "brotli-stream": ("inikep_lzbench", "lz/brotli/", "adapters/brotli_stream/vendor/brotli",
                          ("lz/brotli/common/", "lz/brotli/enc/", "lz/brotli/dec/", "lz/brotli/include/"),
                          ("lz/brotli/LICENSE", "lz/brotli/CHANGELOG.md", "lz/brotli/README"), ()),
        "deflate-zlib": ("inikep_lzbench", "lz/zlib/", "adapters/deflate_zlib/vendor/zlib", ("lz/zlib/",), (), ()),
        "lz4-frame": ("inikep_lzbench", "lz/lz4/", "adapters/lz4_frame/vendor/lz4", (),
                      tuple("lz/lz4/" + p for p in ("LICENSE", "lib/LICENSE", "lib/lz4.c", "lib/lz4.h",
                           "lib/lz4frame.c", "lib/lz4frame.h", "lib/lz4frame_static.h", "lib/lz4hc.c",
                           "lib/lz4hc.h", "lib/xxhash.c", "lib/xxhash.h")), ()),
        "snappy-raw": ("inikep_lzbench", "lz/snappy/", "adapters/snappy_raw/vendor/snappy", (),
                       tuple("lz/snappy/" + p for p in ("COPYING", "format_description.txt", "snappy-internal.h",
                            "snappy-sinksource.cc", "snappy-sinksource.h", "snappy-stubs-internal.cc",
                            "snappy-stubs-internal.h", "snappy-stubs-public.h", "snappy.cc", "snappy.h")), ()),
        "zstd-frame": ("inikep_lzbench", "lz/zstd/", "adapters/zstd_frame/vendor/zstd",
                       ("lz/zstd/lib/common/", "lz/zstd/lib/compress/", "lz/zstd/lib/decompress/"),
                       ("lz/zstd/LICENSE", "lz/zstd/COPYING", "lz/zstd/lib/zstd.h", "lz/zstd/lib/zstd_errors.h"),
                       ("lz/zstd/lib/compress/zstdmt_compress.c", "lz/zstd/lib/decompress/huf_decompress_amd64.S")),
    }
    entropy_names = tuple("lib/" + name for name in ("bitstream.h", "compiler.h", "debug.h",
                          "entropy_common.c", "error_private.h", "error_public.h", "fse.h",
                          "fse_compress.c", "fse_decompress.c", "hist.c", "hist.h", "huf.h",
                          "huf_compress.c", "huf_decompress.c", "mem.h"))
    for key in ("fse", "huff0"):
        selections[key] = ("Cyan4973_FiniteStateEntropy", "lib/", "adapters/entropy_fse/vendor/lib",
                           (), entropy_names, ())
    for key in ("alp", "alp-rd"):
        selections[key] = ("cwida_ALP", "", "adapters/alp/vendor/alp",
                           ("include/alp/", "include/fastlanes/"),
                           ("src/fastlanes_ffor.cpp", "src/fastlanes_unffor.cpp",
                            "src/fastlanes_generated_ffor.cpp", "src/fastlanes_generated_unffor.cpp"),
                           ("include/alp/falp.hpp", "include/alp/storer.hpp"))
    sprintz_names = tuple("sprintz/" + name for name in ("bitpack.h", "debug_utils.hpp", "format.cpp", "format.h",
                         "macros.h", "query.hpp", "sprintz.cpp", "sprintz.h", "sprintz_delta.h",
                         "sprintz_delta_lowdim.cpp", "sprintz_delta_rle.cpp", "sprintz_xff.h",
                         "sprintz_xff_lowdim.cpp", "sprintz_xff_rle.cpp", "traits.hpp", "transpose.h", "util.h"))
    for key in ("sprintz-delta", "sprintz-fire", "sprintz-delta-u8", "sprintz-fire-u8"):
        selections[key] = ("sprintz-lzbench", "sprintz/", "adapters/sprintz/vendor/sprintz",
                           (), sprintz_names, ())
    rows = []
    for previous in old["rows"]:
        key = previous["codec_key"]
        path, source = source_documents[previous["source_artifact_id"].split(":")[-1]]
        identity = source["identity"]
        row = {"codec_key": key, "algorithm_id": previous["algorithm_id"],
               "source_artifact_id": previous["source_artifact_id"], "source_record": ref(path),
               "previous_generic_inventory_status": previous["source_inventory"]["closure_status"],
               "source_semantic_parity": "NOT_GRANTED_BY_SOURCE_FILE_VERIFICATION",
               "full_n_g_cap_gates": "NOT_GRANTED_BY_SOURCE_FILE_VERIFICATION",
               "formal_performance": "NOT_EXECUTED_BY_THIS_READ_ONLY_DRIVER"}
        if identity.get("api_files"):
            prefix = Path(identity["api_files"][0]["path"]).parts[:4]
            vendor = Path(*prefix)
            expected = {str(Path(x["path"]).relative_to(vendor)): x["sha256"] for x in identity["api_files"]}
            if len(expected) != len(identity["api_files"]):
                raise RuntimeError("duplicate frozen API path")
            lock_files = (completed_lock["packages"][identity["package"]]["files"]
                          if str(vendor).startswith("adapters/completed_rewrites")
                          else api_lock["algorithms"][key]["files"])
            if {(x["path"], x["sha256"]) for x in lock_files} != {(x["path"], x["sha256"]) for x in identity["api_files"]}:
                raise RuntimeError("independent existing package/API lock differs from registration: " + key)
            row["installed_source_closure"] = verify_manifest(ROOT / vendor, expected, exact=True)
            row["installed_source_closure"]["scope"] = "COMPLETE_EXISTING_FROZEN_NATIVE_PACKAGE_FILES_NOT_COMPLETE_UPSTREAM_PACKAGE"
            if "source_manifest" in identity:
                manifest_path = ROOT / identity["source_manifest"]["path"]
                if digest(manifest_path.read_bytes()) != identity["source_manifest"]["sha256"]:
                    raise RuntimeError("source manifest drift")
                commits = re.findall(r"^source_commit:\s*['\"]?([0-9a-f]{40})['\"]?\s*$",
                                     manifest_path.read_text(), flags=re.MULTILINE)
                if len(commits) != 1:
                    raise RuntimeError("source manifest must contain exactly one unambiguous commit")
                repo_name = {"abba": "nla-group_ABBA", "fabba": "nla-group_fABBA",
                             "deepzip": "mohit1997_DeepZip", "dzip": "mohit1997_DZip"}[identity["package"]]
                row["upstream_source_manifest"] = ref(manifest_path)
                row["declared_upstream_commit_matches_authority"] = commits[0] == REPOSITORIES[repo_name]
            else:
                provenance_path = ROOT / vendor / "UPSTREAM_PROVENANCE.json"
                provenance = json.loads(provenance_path.read_text())
                repo_name = {"chimp": "panagiotisl_chimp", "elf": "Spatio-Temporal-Lab_elf",
                             "elf-star": "Spatio-Temporal-Lab_SElfStar", "elf-plus": "Spatio-Temporal-Lab_elf",
                             "self-star": "Spatio-Temporal-Lab_SElfStar"}[identity["package"]]
                files = {x["path"]: x["sha256"] for x in authorities[repo_name]["files"] if x["kind"] == "blob"}
                source_lock = provenance["source_lock"]
                row["locked_upstream_source_files"] = [{"path": x["path"], "expected_sha256": x["sha256"],
                                                          "pinned_git_sha256": files.get(x["path"]),
                                                          "status": "PASS" if x["sha256"] == files.get(x["path"]) else "FAIL"}
                                                         for x in source_lock["files"]]
                declared_commit = source_lock.get("commit")
                if declared_commit is None:
                    source_manifest_path = ROOT / "Compression_Rewrite/Source" / identity["package"] / "SOURCE_MANIFEST.yaml"
                    matches = re.findall(r"^source_commit:\s*([0-9a-f]{40})\s*$",
                                         source_manifest_path.read_text(), flags=re.MULTILINE)
                    if len(matches) != 1:
                        raise RuntimeError("missing unambiguous source commit")
                    declared_commit = matches[0]
                    row["upstream_source_manifest"] = ref(source_manifest_path)
                row["declared_upstream_commit"] = declared_commit
                row["declared_upstream_commit_matches_authority"] = declared_commit == REPOSITORIES[repo_name]
                if declared_commit != REPOSITORIES[repo_name]:
                    row["authority_relation"] = "DIFFERENT_PINNED_REVISION_NOT_UPSTREAM_SOURCE_CLOSURE_PASS"
                    for item in row["locked_upstream_source_files"]:
                        item["status"] = "UNKNOWN_DIFFERENT_PINNED_REVISION"
                    row["retained_original_source_snapshot"] = verify_manifest(
                        ROOT / "Compression_Rewrite/Source" / identity["package"] / "upstream",
                        {x["path"]: x["sha256"] for x in source_lock["files"]}, exact=False)
                    row["retained_original_source_snapshot"]["scope"] = "EXISTING_SOURCE_LOCK_SELECTED_FILES_NOT_COMPLETE_MISSING_GIT_REVISION"
            row["upstream_authority"] = ref(output / "authorities" / (repo_name + ".json"))
        elif key == "simdcomp-u32":
            expected = {x["upstream_path"]: x["sha256"] for x in simd_lock["files"]}
            row["installed_source_closure"] = verify_manifest(ROOT / "adapters/simdcomp/vendor/simdcomp", expected, exact=True)
            row["registered_digest_protocol"] = "SHA256_CANONICAL_JSON_OF_EXISTING_SOURCE_LOCK_FILES"
            row["registered_digest_verified"] = digest(canonical(simd_lock["files"])) == identity["source_closure_sha256"]
            upstream = {x["path"]: x["sha256"] for x in authorities["lemire_simdcomp"]["files"] if x["kind"] == "blob"}
            row["source_lock_matches_independent_git"] = all(upstream.get(x) == sha for x, sha in expected.items())
            row["upstream_authority"] = ref(output / "authorities/lemire_simdcomp.json")
        elif key in selections:
            name, prefix, vendor, prefixes, names, excluded = selections[key]
            expected = {p.removeprefix(prefix): sha for p, sha in select(authorities[name], prefixes=prefixes,
                                                                       names=names, excluded=excluded).items()}
            row["installed_source_closure"] = verify_manifest(ROOT / vendor, expected, exact=True)
            row["installed_source_closure"]["scope"] = "DECLARED_NATIVE_SELECTED_BUILD_PROFILE_FROM_INDEPENDENT_PINNED_GIT"
            row["authority_selection"] = {"prefixes": prefixes, "names": names, "excluded": excluded}
            row["upstream_authority"] = ref(output / "authorities" / (name + ".json"))
            row["registered_digest_protocol"] = "UNSPECIFIED_HISTORICAL_PROTOCOL_RETAINED"
            if key in {"sprintz-delta", "sprintz-fire", "sprintz-delta-u8", "sprintz-fire-u8"}:
                data = b"".join((sha + "  sprintz/" + relative + "\n").encode()
                                for relative, sha in sorted(expected.items()))
                row["registered_digest_protocol"] = "SHA256_SORTED_SHA256SUM_TEXT_WITH_VENDOR_RELATIVE_PATHS"
                row["registered_digest_protocol_evidence"] = ref(ROOT / "tools/qualify_sprintz.py")
                row["registered_digest_observed"] = digest(data)
                row["registered_digest_verified"] = digest(data) == identity["source_closure_sha256"]
        elif key == "lzss-raw":
            expected = {x["path"]: x["sha256"] for x in identity["source_closure"]}
            row["installed_source_closure"] = verify_manifest(ROOT, expected, exact=False)
            row["installed_source_closure"]["scope"] = "EXPLICIT_FIVE_FILE_REGISTERED_CPP_TRANSLATION_PROFILE"
            row["upstream_authority"] = ref(output / "authorities/alexkazik_lzss.json")
        else:
            old_source = previous["source_inventory"]
            row["installed_source_closure"] = {
                "status": "UNKNOWN_NEEDS_PROFILE_SPECIFIC_MAPPING",
                "scope": "NO_NEW_EXPECTATION_GENERATED_FROM_INSTALLED_FILES",
                "previous_vendor_tree_status": [x["state"] for x in old_source["observed_vendor_trees"]]}
            name = ("cwida_ALP" if key in {"alp", "alp-rd"} else "sprintz-lzbench" if key.startswith("sprintz-")
                    else "and-gue_NeaTS" if key in {"neats-lossless-i64", "leats-lossless-i64"}
                    else "Spatio-Temporal-Lab_Serf" if key.startswith("serf-")
                    else "LLNL_zfp" if key == "zfp-accuracy-1d" else None)
            if name:
                row["upstream_authority"] = ref(output / "authorities" / (name + ".json"))
            else:
                row["upstream_authority"] = {"status": "UNKNOWN_INDEPENDENT_AUTHORITY_NOT_LOCALLY_PRESENT"}
            trees = previous["source_inventory"]["observed_vendor_trees"]
            if len(trees) == 1 and previous["source_inventory"]["closure_status"] == "HASHES_VERIFIED_VENDOR_TREES":
                vendor = ROOT / trees[0]["path"]
                inventory, excluded, links = physical_inventory(vendor)
                observed = digest(b"".join(relative.encode() + b"\0" + (vendor / relative).read_bytes()
                                           for relative in sorted(inventory)))
                row["installed_source_closure"] = {
                    "status": "PASS" if observed == identity["source_closure_sha256"] and not links else "FAIL",
                    "scope": "COMPLETE_REGISTERED_SELECTED_VENDOR_TREE_NOT_COMPLETE_UPSTREAM_REPOSITORY",
                    "registered_digest_protocol": "RELATIVE_PATH_NUL_FILE_BYTES_V1",
                    "declared_sha256": identity["source_closure_sha256"], "observed_sha256": observed,
                    "expected_count": identity.get("source_closure_file_count"), "observed_count": len(inventory),
                    "source_expectation": "EXISTING_REGISTERED_SHA256_PRESERVED",
                    "cache_files_excluded": excluded, "symlinks_rejected": links}
                if identity.get("source_closure_file_count", len(inventory)) != len(inventory):
                    row["installed_source_closure"]["status"] = "FAIL"
        rows.append(row)
    negative = mutation_tests()
    after = [ref(x) for x in inputs]
    report = {"schema_version": "tscb.independent-source-closure.v1", "created_at": datetime.now(UTC).isoformat(),
              "root": str(ROOT), "driver": ref(Path(__file__)), "inputs": before,
              "input_snapshot_unchanged": before == after,
              "active_codec_count": len(rows), "rows": rows,
              "installed_source_closure_status_counts": dict(Counter(x["installed_source_closure"]["status"] for x in rows)),
              "authority_count": len(authorities),
              "all_authority_blob_count": sum(x["file_count"] for x in authorities.values()),
              "all_authority_blob_bytes": sum(x["bytes"] for x in authorities.values()),
              "authority_reports": [ref(output / "authorities" / (x + ".json")) for x in authorities],
              "mutation_tests": negative, "full_upstream_semantic_parity_granted": False,
              "full_n_g_cap_granted": False, "formal_granted": False,
              "historical_evidence_rewritten": False, "production_registration_modified": False}
    write_new(output / "report.json", report)
    print(json.dumps({k: report[k] for k in ("active_codec_count", "installed_source_closure_status_counts",
                                           "authority_count", "all_authority_blob_count", "all_authority_blob_bytes",
                                           "input_snapshot_unchanged")}, indent=2), flush=True)
    raise SystemExit(not report["input_snapshot_unchanged"] or any(x["status"] != "PASS" for x in negative)
                     or any(x["installed_source_closure"]["status"].startswith("FAIL") for x in rows))


if __name__ == "__main__":
    main()
