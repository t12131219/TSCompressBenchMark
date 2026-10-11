from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/build_completed_rewrite.py"
spec = importlib.util.spec_from_file_location("completed_builder_under_test", SCRIPT)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def compile_fixture(tmp_path):
    folder = tmp_path / "build"
    cmake = folder / "cmake"
    cmake.mkdir(parents=True)
    source = tmp_path / "source.cpp"
    source.write_text("int main() { return 0; }\n")
    header = tmp_path / "header.hpp"
    header.write_text("#pragma once\n")
    (cmake / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(cmake),
                    "file": str(source),
                    "arguments": ["c++", "-o", "source.cpp.o", "-c", str(source)],
                }
            ]
        )
    )
    dependency = cmake / "source.cpp.o.d"
    dependency.write_text(f"source.cpp.o: {source} \\\n {header}\n")
    return folder, source, header, dependency


def test_compiler_closure_binds_header_bytes(tmp_path):
    folder, source, header, _ = compile_fixture(tmp_path)
    before = {entry["path"]: entry["sha256"] for entry in builder.compiled_dependencies(folder)}
    assert set(before) == {str(source), str(header)}
    header.write_text("#define DIFFERENT_HEADER 1\n")
    after = {entry["path"]: entry["sha256"] for entry in builder.compiled_dependencies(folder)}
    assert before[str(header)] != after[str(header)]


def test_each_compiled_translation_unit_needs_its_own_dependency_file(tmp_path):
    folder, _, header, dependency = compile_fixture(tmp_path)
    dependency.rename(dependency.with_name("unrelated.o.d"))
    with pytest.raises(RuntimeError, match="TU dependency file missing"):
        builder.compiled_dependencies(folder)


def test_depfile_must_include_the_actual_translation_unit(tmp_path):
    folder, _, header, dependency = compile_fixture(tmp_path)
    dependency.write_text(f"source.cpp.o: {header}\n")
    with pytest.raises(RuntimeError, match="TU absent"):
        builder.compiled_dependencies(folder)


def test_missing_compiled_header_cannot_be_signed(tmp_path):
    folder, _, header, _ = compile_fixture(tmp_path)
    header.unlink()
    with pytest.raises(RuntimeError, match="compiled dependency missing"):
        builder.compiled_dependencies(folder)
