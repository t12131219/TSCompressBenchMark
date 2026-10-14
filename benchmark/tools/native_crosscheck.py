"""Direct C native API versus Python bridge byte-for-byte cross-check."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np

from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import Buffer, NativeTiming
from tsbench.build import artifact_path
from tsbench.registry import Registry

ROOT = Path(__file__).resolve().parents[2]


def crosscheck(root: Path = ROOT, output: Path | None = None) -> dict:
    compiler = shutil.which(os.environ.get("CC", "cc"))
    if compiler is None:
        raise RuntimeError("C compiler unavailable for native cross-check")
    evidence = {"schema": "tsbench.native-crosscheck-evidence/1", "cases": [],
                "timing_scope": "diagnostic native API; incomparable with object_memory",
                "encode_includes": ["compress", "finalize"], "decode_includes": ["decompress"],
                "excluded": ["create/reset/destroy", "bound", "allocation", "file IO", "verification", "Python FFI", "outer envelope"],
                "independent_decoder_handle": True, "reference_source_sha256": hashlib.sha256((root / "benchmark/tests/native/reference.c").read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix="tsbench-native-crosscheck-") as temporary:
        temporary = Path(temporary)
        executable = temporary / "reference"
        command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(root / "native/include"),
                   str(root / "benchmark/tests/native/reference.c"), "-ldl", "-o", str(executable)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        evidence["compile_command"] = command
        registry = Registry(root)
        for key in ("zstd-frame", "lzss-raw"):
            library = artifact_path(root, key)
            if not library.is_file():
                raise FileNotFoundError(f"native library missing: run tsbench build {key}")
            params = registry.resolve_params(key)
            bridge = create_bridge(root, key)
            config = ({"compression_level": params["compression_level"], "content_checksum": params["content_checksum"]}
                      if key == "zstd-frame" else {name: params[name] for name in ("ei", "ej", "initial_byte")})
            for length in (0, 1, 257):
                original = (np.arange(length) % 251).astype(np.uint8)
                source = temporary / "input.bin"
                payload = temporary / "payload.bin"
                restored = temporary / "restored.bin"
                source.write_bytes(original.tobytes())
                done = subprocess.run([str(executable), str(library), key, str(source),
                                       json.dumps(config, sort_keys=True, separators=(",", ":")), str(payload), str(restored)],
                                      check=True, capture_output=True, text=True, timeout=30)
                native = json.loads(done.stdout)
                python_payload = bridge.encode(original, params)
                python_restored = bridge.decode(payload.read_bytes(), original.dtype, original.shape, params)
                if python_payload != payload.read_bytes() or python_restored.tobytes() != restored.read_bytes():
                    raise AssertionError(f"{key} length={length}: native/Python bytes differ")
                if restored.read_bytes() != original.tobytes():
                    raise AssertionError(f"{key} length={length}: original bytes not restored")
                if native["buffer_struct_bytes"] != ctypes.sizeof(Buffer):
                    raise AssertionError("C/Python ABI buffer struct size differs")
                if native["buffer_offsets"] != [getattr(Buffer, field).offset for field, _ in Buffer._fields_]:
                    raise AssertionError("C/Python ABI buffer field offsets differ")
                if native["native_timing_struct_bytes"] != ctypes.sizeof(NativeTiming):
                    raise AssertionError("C/Python native timer struct size differs")
                if native["native_timing_offsets"] != [getattr(NativeTiming, field).offset for field, _ in NativeTiming._fields_]:
                    raise AssertionError("C/Python native timer field offsets differ")
                evidence["cases"].append({"codec": key, "input_length": length, **native,
                                          "native_library": str(library), "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                                          "input_sha256": hashlib.sha256(original.tobytes()).hexdigest(),
                                          "payload_sha256": hashlib.sha256(python_payload).hexdigest(),
                                          "python_payload_bytes": len(python_payload), "payload_bytewise_equal": True,
                                          "restored_bytewise_equal": True, "buffer_struct_size_equal": True,
                                          "buffer_field_offsets_equal": True, "native_timing_layout_equal": True})
    evidence["passed"] = all(row["payload_bytewise_equal"] and row["restored_bytewise_equal"] for row in evidence["cases"])
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/research/native_crosscheck.json")
    args = parser.parse_args()
    result = crosscheck(output=args.output)
    print(json.dumps({"passed": result["passed"], "cases": len(result["cases"]), "evidence": str(args.output)}, indent=2))
