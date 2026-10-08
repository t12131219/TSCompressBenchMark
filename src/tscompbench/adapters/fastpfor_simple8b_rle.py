"""RLE-specific contracts on the existing FastPFOR descriptor/lifecycle SDK."""

from __future__ import annotations

import hashlib
import json
import shlex
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tscompbench.accounting import AccountingLedger
from tscompbench.codecs import CodecManifest
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, RoutedInput
from tscompbench.ids import stable_id

from .fastpfor_simple import FRAME, FastPFORSimpleSession, _Library

KEY = "fastpfor-simple8b-rle-u32"
WIDTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 30, 60)
COUNTS = (0, 60, 30, 20, 15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1)


def execution_artifacts(root: Path, manifest: CodecManifest) -> tuple[Path, tuple[Path, ...]]:
    adapter = manifest.document["adapter"]
    relative = "build/adapters/fastpfor_simple8b_rle/20261007-2/release/libtscb_fastpfor_simple8b_rle.so"
    if manifest.key != KEY or adapter.get("artifact_path") != relative:
        raise ExecutionContractError("RLE artifact identity differs")
    artifact = root / relative
    record_path = artifact.parent / "build-record.json"
    record = json.loads(record_path.read_text())
    component = root / "adapters/fastpfor_simple8b_rle"
    lock_path, patch_path = component / "SOURCE_LOCK.json", component / "PATCH_LOCK.json"
    lock = json.loads(lock_path.read_text())
    if (
        record.get("status") != "PASS"
        or record.get("profile") != "release"
        or record.get("build_id") != "20261007-2"
        or record.get("algorithm") != "fastpfor-simple8b-rle-source"
        or record.get("source_isa") != "BASELINE_X86_64_NO_AUTOVECTORIZATION"
        or record.get("runtime_fallback") is not False
        or record.get("artifact", {}).get("path") != relative
        or len(record.get("objects", [])) != 1
        or len(record.get("dependency_files", [])) != 1
        or len(record.get("patches", [])) != 1
        or not record.get("generated_source_files")
        or not record.get("binding_sources")
        or not record.get("runtime_dependencies")
        or record.get("source_files") != lock["files"]
        or lock.get("commit") != "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
        or record.get("source_lock_sha256") != hashlib.sha256(lock_path.read_bytes()).hexdigest()
        or record.get("patch_lock_sha256") != hashlib.sha256(patch_path.read_bytes()).hexdigest()
        or not any("-Wl,-Bsymbolic" in item["command"] for item in record["commands"])
        or any(item["returncode"] != 0 for item in record["commands"])
    ):
        raise ExecutionContractError("RLE completed patched build evidence differs")
    python_closure = adapter.get("python_source_closure", [])
    required = {
        "src/tscompbench/adapters/factory.py",
        "src/tscompbench/adapters/fastpfor_simple.py",
        "src/tscompbench/adapters/fastpfor_simple8b_rle.py",
        "src/tscompbench/adapters/deflate_zlib.py",
        "src/tscompbench/adapters/native_timing.py",
        "src/tscompbench/planning/resolution.py",
        "src/tscompbench/execution/protocol.py",
        "src/tscompbench/execution/repetition.py",
    }
    if not required <= {item["path"] for item in python_closure}:
        raise ExecutionContractError("RLE Python execution closure missing")
    dependency = root / record["dependency_files"][0]["path"]
    actual = {Path(p).resolve() for p in shlex.split(
        dependency.read_text().replace("\\\n", " ").split(":", 1)[1])}
    declared = record["compiled_source_closure"]
    if len(declared) != len(actual) or {root / item["path"] for item in declared} != actual:
        raise ExecutionContractError("RLE compiler closure incomplete")
    entries = [record["artifact"], *python_closure]
    for field in ("source_files", "binding_sources", "generated_source_files", "patches",
                  "objects", "dependency_files", "compiled_source_closure", "runtime_dependencies"):
        entries += record[field]
    paths = [record_path]
    for item in entries:
        p = Path(item["path"])
        if ".." in p.parts:
            raise ExecutionContractError("RLE dependency path escapes root")
        path = root / p
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise ExecutionContractError("RLE execution dependency drift: " + str(path))
        paths.append(path)
    return artifact, tuple(dict.fromkeys(paths))


class _RLELibrary(_Library):
    EXPECTED_MANIFEST = {
        **_Library.EXPECTED_MANIFEST,
        "algorithm": "fastpfor-simple8b-rle-source",
        "frame": "8BR1",
        "source_patch": "COMPLETE_LENGTH_WORD_ACCESS_AND_TAIL",
        "value_bits_max": 32,
    }


@dataclass(frozen=True)
class FastPFORSimple8bRLEAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str = KEY

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> FastPFORSimple8bRLESession:
        return FastPFORSimple8bRLESession(self.library_path, self.algorithm, parameters)


class FastPFORSimple8bRLESession(FastPFORSimpleSession):
    KEYS = {KEY: "SIMPLE8B_RLE"}
    MAGIC = b"TSCB8BC1"
    CONTAINER_SCHEMA = "tscb.simple8b-rle-container.v1"
    VALUE_BITS = 32
    NATIVE_LIBRARY = _RLELibrary

    def _validate_frame(self, frame: memoryview, count: int, params: dict) -> None:
        magic, n, kind, marked, words, reserved0, reserved1 = FRAME.unpack_from(frame)
        if (
            magic != b"TSCB8BR1"
            or n != count
            or kind != 0
            or marked != int(params["mark_length"])
            or reserved0
            or reserved1
            or not marked + (2 if count else 0) <= words <= marked + count * 2
            or (words - marked) % 2
            or len(frame) != 40 + words * 4
        ):
            raise ExecutionContractError("RLE descriptor/native frame mismatch")

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._open()
        if not self._finalized:
            raise ExecutionContractError("RLE accounting before finalize")
        header, info, frame = self._parse(stream)
        expected, _ = self._payload(routed)
        if header != self._header or header != expected or hashlib.sha256(stream).digest() != self._digest:
            raise ExecutionContractError("RLE encoded object changed")
        marked = int(info["parameters"]["mark_length"])
        words = (len(frame) - 40) // 4
        count = info["count"]
        if marked and struct.unpack_from("<I", frame, 32)[0] != count:
            raise ExecutionContractError("RLE source count marker differs")
        value_bits = padding_bits = count_bits = logical = 0
        for (word,) in struct.iter_unpack("<Q", frame[32 + marked * 4 : -8]):
            selector, payload = word >> 60, word & ((1 << 60) - 1)
            remaining = count - logical
            if not selector or remaining <= 0:
                raise ExecutionContractError("RLE accounting selector/count differs")
            if selector == 15:
                run = payload >> 32
                if not 0 < run <= remaining:
                    raise ExecutionContractError("RLE accounting run count differs")
                logical += run
                count_bits += 28
                value_bits += 32
            else:
                used = min(remaining, COUNTS[selector])
                width = WIDTHS[selector]
                if payload >> (used * width) or (width == 60 and payload >> 32):
                    raise ExecutionContractError("RLE accounting value/tail differs")
                logical += used
                value_bits += used * min(width, 32)
                padding_bits += 60 - used * min(width, 32)
        if logical != count:
            raise ExecutionContractError("RLE accounting incomplete logical object")
        native = self._json("tscb_get_accounting_json")
        expected_native = {
            "container_bits": 64,
            "metadata_bits": 192 + marked * 32 + ((words - marked) // 2) * 4 + count_bits,
            "checksum_bits": 64,
            "value_bits": value_bits,
            "padding_bits": padding_bits,
            "final_bits": len(frame) * 8,
            "count": count,
            "original_payload_bytes": words * 4,
            "external_padding_bytes": 0,
        }
        if native != expected_native or any(type(v) is not int or v < 0 for v in native.values()):
            raise ExecutionContractError("RLE native ledger mismatch")
        return AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=value_bits,
            padding_bits=padding_bits,
            metadata_bits=len(header) * 8 + native["metadata_bits"],
            container_bits=12 * 8 + native["container_bits"],
            checksum_bits=32 * 8 + native["checksum_bits"],
            accounting_method="EXACT_DESCRIPTOR_8BR1_RLE_COUNTS_SELECTORS_VALUES_TAIL_PADDING_CHECKSUM",
        )
