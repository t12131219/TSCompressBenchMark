from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("general_build_codec", ROOT / "tools/build_codec.py")
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.mark.parametrize("compiler,extension", [("cc", ".c"), ("clang++", ".cc")])
def test_real_multi_tu_compilation_captures_each_header_and_object(
    tmp_path, monkeypatch, compiler, extension
):
    if shutil.which(compiler) is None or shutil.which("ldd") is None:
        pytest.skip("native compiler and loader inspection are required")
    monkeypatch.setattr(builder, "PROJECT_ROOT", tmp_path)
    (tmp_path / "first.h").write_text("int first(void);\n")
    (tmp_path / "second.h").write_text("int second(void);\n")
    first = tmp_path / ("first" + extension)
    second = tmp_path / ("second" + extension)
    first.write_text('#include "first.h"\n#include <stdint.h>\nint first(void) { return 7; }\n')
    second.write_text('#include "second.h"\nint second(void) { return 9; }\n')
    output = tmp_path / "libfixture.so"
    evidence, _ = builder._compile_with_dependencies(
        [compiler, "-fPIC", "-shared", str(first), str(second), "-o", str(output)],
        output,
    )
    assert output.is_file()
    assert len(evidence["translation_unit_commands"]) == 2
    assert len(evidence["objects"]) == len(evidence["compiler_dependency_files"]) == 2
    paths = {entry["path"] for entry in evidence["compiled_source_closure"]}
    assert {"first.h", "second.h", first.name, second.name} <= paths
    assert any(Path(path).name == "stdint.h" for path in paths)
    assert str(first) not in evidence["link_command"]
    assert str(second) not in evidence["link_command"]
    for entry in evidence["objects"] + evidence["compiler_dependency_files"]:
        assert builder._sha256(tmp_path / entry["path"]) == entry["sha256"]
    assert evidence["toolchain_files"]
    roles = {program["role"] for program in evidence["toolchain_programs"]}
    assert {"compiler_driver", "linker"} <= roles
    assert (
        "integrated_compiler_frontend" if compiler == "clang++" else "compiler_frontend"
    ) in roles
    assert json.dumps(evidence)


def test_make_dependency_paths_with_whitespace_are_preserved(tmp_path):
    header = tmp_path / "header with space.h"
    header.write_text("/* compiler dependency fixture */\n")
    depfile = tmp_path / "fixture.o.d"
    depfile.write_text("fixture.o: header\\ with\\ space.h\n")
    assert builder._make_dependencies(depfile, directory=tmp_path) == [header]


def test_new_output_root_refuses_to_replace_existing_build(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    monkeypatch.setattr(builder, "PROJECT_ROOT", tmp_path)
    destination = tmp_path / "new-builds/lz4_frame/release"
    destination.mkdir(parents=True)
    old = destination / "build-record.json"
    old.write_bytes(b"preserved evidence")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        builder._build("lz4-frame", "release", output_root=tmp_path / "new-builds")
    assert old.read_bytes() == b"preserved evidence"


def test_output_root_must_stay_in_project(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    monkeypatch.setattr(builder, "PROJECT_ROOT", tmp_path / "project")
    with pytest.raises(ValueError, match="inside the project"):
        builder._build("lz4-frame", "release", output_root=tmp_path / "external")
    assert not (tmp_path / "external").exists()
