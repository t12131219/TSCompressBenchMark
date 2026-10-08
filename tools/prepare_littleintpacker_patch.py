"""Generate a locked build-only zero-width/unaligned word-access correction."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path

from freeze_littleintpacker_source import ADAPTER, ROOT

EXPECTED = {
    "bitpacking32.c": (32, 528),
    "turbobitpacking32.c": (64, 272),
    "scpacking32.c": (64, 272),
    "bmipacking32.c": (64, 272),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corrected(original: str, name: str) -> tuple[str, dict]:
    width, words = EXPECTED[name]
    declaration = (
        rf"(?:const )?uint{width}_t \* pw{width} = \*\((?:const )?uint{width}_t \*\*\) pw;"
    )
    result, declarations = re.subn(declaration, "/* word accesses use memcpy below */", original)
    result, stores = re.subn(
        rf"pw{width}\[(\d+)\] = ([^;]+);",
        rf"tscb_store{width}(*pw + \1 * {width // 8}, \2);",
        result,
    )
    result, loads = re.subn(
        rf"pw{width}\[(\d+)\]",
        rf"tscb_load{width}(*pw + \1 * {width // 8})",
        result,
    )
    result, zeros = re.subn(
        r"memset\(\*pout,0,32\);", "memset(*pout,0,32 * sizeof(uint32_t));", result
    )
    if (declarations, stores, loads, zeros) != (64, words, words, 1):
        raise RuntimeError("unexpected generated-source pattern: " + name)
    if re.search(r"\bpw(?:32|64)\b", result):
        raise RuntimeError("unconverted word pointer in corrected source: " + name)
    helper = f"""/* TSCB build-only correction: preserve original packing grammar/kernel calls;
 * fix zero-width output size and use memcpy for word accesses, including odd
 * bit-width offsets. Original vendor bytes are retained separately. */
static inline uint{width}_t tscb_load{width}(const uint8_t *p) {{
    uint{width}_t value;
    memcpy(&value, p, sizeof(value));
    return value;
}}
static inline void tscb_store{width}(uint8_t *p, uint{width}_t value) {{
    memcpy(p, &value, sizeof(value));
}}
"""
    result = result.replace('#include "bitpacking.h"', '#include "bitpacking.h"\n\n' + helper, 1)
    return result, {
        "zero_width_fixes": zeros,
        "pointer_casts_removed": declarations,
        "word_loads": loads,
        "word_stores": stores,
        "word_bits": width,
    }


def main() -> None:
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    for item in lock["files"]:
        if sha((ROOT / item["path"]).read_bytes()) != item["sha256"]:
            raise RuntimeError("original source drift")
    hunks, changes = [], []
    for name in EXPECTED:
        original = (ADAPTER / "vendor/littleintpacker/src" / name).read_text()
        output, counts = corrected(original, name)
        hunks.extend(
            difflib.unified_diff(
                original.splitlines(True),
                output.splitlines(True),
                fromfile="a/src/" + name,
                tofile="b/src/" + name,
            )
        )
        changes.append(
            {
                "upstream_path": "src/" + name,
                "original_sha256": sha(original.encode()),
                "patched_sha256": sha(output.encode()),
                **counts,
            }
        )
    patch = ADAPTER / "patches/0001-zero-width-and-word-access.patch"
    patch.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(hunks).encode()
    if patch.exists() and patch.read_bytes() != data:
        raise RuntimeError("existing correction patch differs; review before replacing")
    patch.write_bytes(data)
    document = {
        "schema_version": "tscb.littleintpacker-patch-lock.v1",
        "source_lock_sha256": sha((ADAPTER / "SOURCE_LOCK.json").read_bytes()),
        "patch": {"path": str(patch.relative_to(ROOT)), "sha256": sha(data)},
        "changes": changes,
        "generator_sha256": sha(Path(__file__).read_bytes()),
        "original_source_modified": False,
        "semantic_change": "FIX_ZERO_WIDTH_DECODER_NO_WIRE_OR_KERNEL_SELECTION_CHANGE",
        "alignment_change": "MEMCPY_WORD_ACCESS_PRESERVES_BYTE_COUNT_AND_PADDING_REQUIREMENTS",
        "bounded_abi": "PENDING",
        "benchmark_five_layers": "PENDING",
    }
    (ADAPTER / "PATCH_LOCK.json").write_text(json.dumps(document, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "BUILD_ONLY_PATCH_PREPARED",
                "files": len(changes),
                "patch_sha256": sha(data),
            }
        )
    )


if __name__ == "__main__":
    main()
