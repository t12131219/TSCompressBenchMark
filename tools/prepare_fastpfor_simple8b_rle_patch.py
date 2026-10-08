"""Generate the explicit build-only RLE returned-count/alignment/tail correction."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from freeze_fastpfor_simple8b_rle_source import ADAPTER, ROOT, sha

PATCH_NAME = "0001-complete-length-word-access-and-tail.patch"


def corrected(source: str) -> str:
    replacements = (
        ("      output[outPos++] = outVal;",
         "      memcpy(reinterpret_cast<unsigned char *>(output) +\n"
         "                 size_t(outPos++) * sizeof(uint64_t), &outVal, sizeof(outVal));"),
        ("      uint64_t val = input[inPos++];",
         "      uint64_t val;\n"
         "      memcpy(&val, reinterpret_cast<const unsigned char *>(input) +\n"
         "                       size_t(inPos++) * sizeof(uint64_t), sizeof(val));"),
        ("        for (; i < intNum; i += 8) {",
         "        for (; i + 8 <= intNum; i += 8) {"),
        ("    nvalue = count * 2;",
         "    nvalue = size_t(count) * 2 + (MarkLength ? 1 : 0);"),
    )
    for before, after in replacements:
        if source.count(before) != 1:
            raise RuntimeError("source correction pattern changed: " + before)
        source = source.replace(before, after)
    return source


def main() -> None:
    lock_path = ADAPTER / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    for item in lock["files"]:
        if sha((ROOT / item["path"]).read_bytes()) != item["sha256"]:
            raise RuntimeError("original source drift")
    original = (ADAPTER / "vendor/fastpfor/headers/simple8b_rle.h").read_text()
    result = corrected(original)
    patch = "".join(difflib.unified_diff(
        original.splitlines(True), result.splitlines(True),
        fromfile="a/headers/simple8b_rle.h", tofile="b/headers/simple8b_rle.h",
    )).encode()
    path = ADAPTER / "patches" / PATCH_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != patch:
        raise RuntimeError("refusing to overwrite changed patch")
    path.write_bytes(patch)
    document = {
        "schema_version": "tscb.fastpfor-simple8b-rle-patch-lock.v1",
        "source_lock_sha256": sha(lock_path.read_bytes()),
        "patch": {"path": str(path.relative_to(ROOT)), "sha256": sha(patch)},
        "original_sha256": sha(original.encode()), "patched_sha256": sha(result.encode()),
        "generator_sha256": sha(Path(__file__).read_bytes()),
        "changes": ["MEMCPY_PACKED_UINT64_LOAD_AND_STORE", "ONLY_FULL_EIGHT_VALUE_UNROLLS",
                    "RETURN_MARKED_HEADER_PLUS_PAYLOAD_WORDS"],
        "selector_table_and_rle_selection_changed": False,
        "original_source_modified": False,
        "known_remaining_source_limitations": [
            "ENCODER_IGNORES_OUTPUT_CAPACITY", "DECODER_IGNORES_COMPRESSED_LENGTH",
            "MALFORMED_OR_EOS_COUNTS_NOT_VALIDATED", "UINT32_INPUT_OUTPUT_ALIGNMENT_REQUIRED",
            "SOURCE_COUNT_AND_RLE_MULTIPLICATION_REQUIRE_BOUNDED_LENGTH",
        ],
        "bounded_abi": "PENDING", "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
    }
    target = ADAPTER / "PATCH_LOCK.json"
    if target.exists() and json.loads(target.read_text()) != document:
        raise RuntimeError("refusing to replace changed patch lock")
    target.write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps({"status": "BUILD_ONLY_PATCH_PREPARED_NOT_QUALIFIED",
                      "patch_sha256": document["patch"]["sha256"]}))


if __name__ == "__main__":
    main()
