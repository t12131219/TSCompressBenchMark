from __future__ import annotations

import json
from pathlib import Path

import pytest

from tscompbench.cli import main
from tscompbench.codecs import CodecContractError, CodecRegistry, SourceRegistry
from tscompbench.planning import expand_sweep

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _registry(root=PROJECT_ROOT / "registry/codecs"):
    return CodecRegistry(root, SourceRegistry(PROJECT_ROOT / "registry/sources"))


def test_lz77_selects_the_same_canonical_codec_without_a_new_identity():
    registry = _registry()
    alias = registry.get("lz77")
    canonical = registry.get("deflate-zlib")
    assert alias is canonical
    assert "lz77" not in registry.keys()
    assert len({item.algorithm_id for item in registry.verify_all()}) == len(registry)
    for sweep in ({}, {"compression_level": [1, 6, 9], "window_bits": [9, 15]}):
        assert expand_sweep(alias, sweep) == expand_sweep(canonical, sweep)
    assert alias.document["identity"]["family"] == "DEFLATE"
    document, = registry.alias_documents()
    assert document["key"] == "lz77"
    assert document["canonical_algorithm_id"] == canonical.algorithm_id
    assert document["codec_alias_id"].startswith("v2:codec-alias:sha256:")
    document["evidence"].clear()
    assert registry.alias_documents()[0]["evidence"]


@pytest.mark.parametrize("mutation", [
    "chain", "collision", "missing_evidence", "empty_limitation", "unknown_field",
    "algorithm_identity", "source_identity", "schema", "key_type", "target_type",
])
def test_invalid_aliases_fail_closed(tmp_path, mutation):
    directory = tmp_path / "codecs"
    (directory / "aliases").mkdir(parents=True)
    (directory / "deflate-zlib.json").write_bytes(
        (PROJECT_ROOT / "registry/codecs/deflate-zlib.json").read_bytes()
    )
    document = json.loads((PROJECT_ROOT / "registry/codecs/aliases/lz77.json").read_text())
    patches = {
        "chain": {"canonical_key": "lz77"},
        "collision": {"key": "deflate-zlib"},
        "missing_evidence": {"evidence": []},
        "empty_limitation": {"limitations": [""]},
        "unknown_field": {"silent_fallback": True},
        "algorithm_identity": {"canonical_algorithm_id": "v2:algorithm:sha256:" + "0" * 64},
        "source_identity": {"source_artifact_id": "v2:source-artifact:sha256:" + "0" * 64},
        "schema": {"schema_version": "wrong"},
        "key_type": {"key": []},
        "target_type": {"canonical_key": {}},
    }
    document.update(patches[mutation])
    (directory / "aliases/lz77.json").write_text(json.dumps(document))
    with pytest.raises(CodecContractError):
        _registry(directory)


def test_cli_discloses_mapping_without_counting_it_as_an_independent_codec(capsys):
    assert main(["codecs", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["aliases"][0]["key"] == "lz77"
    assert listed["aliases"][0]["canonical_key"] == "deflate-zlib"
    assert all(codec["key"] != "lz77" for codec in listed["codecs"])
    assert main(["codecs", "verify"]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["alias_count"] == 1
    assert verified["codec_count"] == len(_registry())
