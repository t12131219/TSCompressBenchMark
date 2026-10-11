"""Restore exactly the preserved Java oracle lock in a private directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    import zstandard

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--create-legacy-links",
        action="store_true",
        help="Create missing /tmp oracle paths used by preserved drivers",
    )
    args = parser.parse_args()
    output = args.output_root.resolve()
    downloads = output / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    lock_path = ROOT / "Compression_Rewrite/Source/chimp/ORACLE_ENVIRONMENT_LOCK.json"
    lock = json.loads(lock_path.read_text())
    rows = []
    for package in lock["packages"]:
        target = downloads / package["name"]
        if not target.exists():
            temporary = target.with_name(target.name + ".download")
            with (
                urllib.request.urlopen(package["url"], timeout=30) as source,
                temporary.open("wb") as destination,
            ):
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
            if sha(temporary) != package["sha256"]:
                raise SystemExit("Downloaded oracle dependency SHA mismatch")
            temporary.rename(target)
        if sha(target) != package["sha256"]:
            raise SystemExit("Cached oracle dependency SHA mismatch: " + str(target))
        rows.append({**package, "path": str(target), "actual_sha256": sha(target)})
    java_home = output / "java8"
    if not java_home.exists():
        java_home.mkdir()
        archive = downloads / next(
            p["name"] for p in lock["packages"] if p["name"].endswith(".conda")
        )
        with zipfile.ZipFile(archive) as package:
            member = next(n for n in package.namelist() if n.startswith("pkg-"))
            with (
                package.open(member) as source,
                zstandard.ZstdDecompressor().stream_reader(source) as reader,
            ):
                with tarfile.open(fileobj=reader, mode="r|") as contents:
                    contents.extractall(java_home, filter="data")
    result = subprocess.run(
        [str(java_home / "bin/java"), "-version"], capture_output=True, text=True, check=True
    )
    version = result.stdout + result.stderr
    if version != lock["version"]:
        raise SystemExit("Restored Java version differs from the preserved lock")
    links = []
    if args.create_legacy_links:
        for location, destination in (
            ("/tmp/tscb-elf-java8", java_home),
            ("/tmp/tscb-elf-oracle-downloads", downloads),
        ):
            path = Path(location)
            if path.exists() or path.is_symlink():
                if path.resolve() != destination:
                    raise SystemExit("Refusing to replace an existing oracle path: " + location)
            else:
                path.symlink_to(destination, target_is_directory=True)
            links.append({"path": location, "target": str(destination)})
    report = {
        "schema_version": 1,
        "status": "PASS_EXACT_JAVA_ORACLE_DEPENDENCY_LOCK",
        "driver_sha256": sha(Path(__file__)),
        "lock_sha256": sha(lock_path),
        "packages": rows,
        "java_home": str(java_home),
        "java_version": version,
        "java_sha256": sha(java_home / "bin/java"),
        "javac_sha256": sha(java_home / "bin/javac"),
        "legacy_links": links,
        "source_execution_or_parity_granted": False,
    }
    (output / "restoration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])


if __name__ == "__main__":
    main()
