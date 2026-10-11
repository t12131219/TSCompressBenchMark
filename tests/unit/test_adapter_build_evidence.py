"""Factory rejects missing or altered consumed artifacts before native loading."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from tscompbench.adapters.factory import AdapterFactoryError, adapter_artifacts, create_adapter
from tscompbench.ids import canonical_json_bytes


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value=b"fixture"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def fixture(root, *, saved_command=True):
    artifact = write(root / "build/adapters/lz4_frame/release/libtscb_lz4_frame.so")
    for name in (
        "lz4_frame",
        "native_timing",
        "native_streaming",
        "byte_container",
        "factory",
        "build_evidence",
        "runtime_evidence",
    ):
        write(root / f"src/tscompbench/adapters/{name}.py")
    source = write(root / "adapters/lz4_frame/native/codec.c")
    header = write(root / "native/include/api.h")
    model = write(root / "assets/model.bin")
    command = {
        "schema_version": "tscb.compile-command.v1",
        "profile": "release",
        "command": ["cc", "-shared", "codec.c", "-o", "codec.so"],
    }
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "algorithm": "lz4-frame",
        "profile": "release",
        "artifact": str(artifact.relative_to(root)),
        "artifact_sha256": digest(artifact),
        "compile_commands_sha256": hashlib.sha256(canonical_json_bytes(command)).hexdigest(),
        "command_display": "cc -shared codec.c -o codec.so",
        "compiled_source_closure": [
            {"path": str(p.relative_to(root)), "sha256": digest(p)} for p in (source, header)
        ],
    }
    record_path = artifact.parent / "build-record.json"
    record_path.write_text(json.dumps(record))
    if saved_command:
        (artifact.parent / "compile-command.json").write_text(json.dumps(command))
    manifest = SimpleNamespace(
        key="lz4-frame",
        document={
            "identity": {"family": "LZ4"},
            "adapter": {
                "factory": "LZ4_FRAME_CTYPES_V1",
                "artifact_path": str(artifact.relative_to(root)),
                "models": {"fixed": {"path": "assets/model.bin", "sha256": digest(model)}},
            },
        },
    )
    return manifest, artifact, record_path


@pytest.mark.parametrize(
    "field",
    [
        "compiler_dependency_files",
        "toolchain_files",
        "runtime_dependency_listing",
        "build_driver_files",
    ],
)
@pytest.mark.parametrize("mutation", ["changed", "missing"])
def test_new_actual_build_closure_files_are_verified_before_loading(tmp_path, field, mutation):
    manifest, _, record_path = fixture(tmp_path)
    path = write(tmp_path / "build/dependency")
    record = json.loads(record_path.read_text())
    record[field] = [{"path": "build/dependency", "sha256": digest(path)}]
    record_path.write_text(json.dumps(record))
    assert path in adapter_artifacts(tmp_path, manifest)[1]
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"drift")
    with pytest.raises(AdapterFactoryError, match="execution dependency"):
        adapter_artifacts(tmp_path, manifest)


@pytest.mark.parametrize("saved_command", [False, True])
def test_verified_sources_headers_models_and_control_modules_are_bound(tmp_path, saved_command):
    manifest, artifact, _ = fixture(tmp_path, saved_command=saved_command)
    actual, support = adapter_artifacts(tmp_path, manifest)
    assert actual == artifact
    for path in (
        "adapters/lz4_frame/native/codec.c",
        "native/include/api.h",
        "assets/model.bin",
        "src/tscompbench/adapters/byte_container.py",
        "src/tscompbench/adapters/native_streaming.py",
        "src/tscompbench/adapters/native_timing.py",
        "src/tscompbench/adapters/build_evidence.py",
    ):
        assert tmp_path / path in support
    assert len(support) == len(set(support))


@pytest.mark.parametrize(
    "target",
    [
        "build/adapters/lz4_frame/release/libtscb_lz4_frame.so",
        "adapters/lz4_frame/native/codec.c",
        "native/include/api.h",
        "assets/model.bin",
    ],
)
@pytest.mark.parametrize("mutation", ["changed", "missing"])
def test_factory_checks_every_declared_input_before_loading(
    tmp_path, monkeypatch, target, mutation
):
    manifest, _, _ = fixture(tmp_path)
    path = tmp_path / target
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"different")

    def must_not_load(*args):
        pytest.fail("native adapter must not load after failed evidence verification")

    monkeypatch.setattr("tscompbench.adapters.factory.Lz4FrameAdapter", must_not_load)
    with pytest.raises(AdapterFactoryError, match="drift|missing"):
        create_adapter(tmp_path, manifest)


@pytest.mark.parametrize(
    "damage", ["algorithm", "profile", "artifact", "status", "hash", "list", "command", "record"]
)
def test_factory_does_not_accept_an_unrelated_or_unverifiable_build(tmp_path, damage):
    manifest, artifact, path = fixture(tmp_path)
    record = json.loads(path.read_text())
    if damage == "record":
        path.unlink()
    elif damage == "command":
        command_path = artifact.parent / "compile-command.json"
        command = json.loads(command_path.read_text())
        command["command"].append("-ffast-math")
        command_path.write_text(json.dumps(command))
    else:
        if damage == "algorithm":
            record["algorithm"] = "another-codec"
        elif damage == "profile":
            record["profile"] = "sanitizer"
        elif damage == "artifact":
            record["artifact"] = "build/another.so"
        elif damage == "status":
            record["status"] = "FAIL"
        elif damage == "hash":
            record["artifact_sha256"] = "invalid"
        elif damage == "list":
            record["compiled_source_closure"] = None
        path.write_text(json.dumps(record))
    with pytest.raises(AdapterFactoryError):
        adapter_artifacts(tmp_path, manifest)


@pytest.mark.parametrize("location", ["artifact", "source", "model"])
@pytest.mark.parametrize("kind", ["parent", "absolute", "symlink"])
def test_project_dependencies_cannot_escape_checkout(tmp_path, location, kind):
    root = tmp_path / "checkout"
    manifest, artifact, path = fixture(root)
    outside = write(tmp_path / "outside.bin", b"outside")
    if kind == "symlink":
        relative = "escaped.bin"
        (root / relative).symlink_to(outside)
    else:
        relative = "../outside.bin" if kind == "parent" else str(outside)
    if location == "artifact":
        manifest.document["adapter"]["artifact_path"] = relative
    elif location == "model":
        manifest.document["adapter"]["models"]["fixed"]["path"] = relative
    else:
        record = json.loads(path.read_text())
        record["compiled_source_closure"][0]["path"] = relative
        path.write_text(json.dumps(record))
    with pytest.raises(AdapterFactoryError, match="safe|escapes|drift"):
        adapter_artifacts(root, manifest)


def test_external_pinned_dependency_is_hashed_and_missing_is_rejected(tmp_path):
    root = tmp_path / "checkout"
    manifest, _, path = fixture(root)
    runtime = write(tmp_path / "external/libc.so")
    record = json.loads(path.read_text())
    record["pinned_native_dependencies"] = [{"path": str(runtime), "sha256": digest(runtime)}]
    path.write_text(json.dumps(record))
    assert runtime in adapter_artifacts(root, manifest)[1]
    runtime.unlink()
    with pytest.raises(AdapterFactoryError, match="dependency missing"):
        adapter_artifacts(root, manifest)


def test_legacy_command_text_is_never_executed(tmp_path):
    manifest, _, path = fixture(tmp_path, saved_command=False)
    record = json.loads(path.read_text())
    record["command_display"] = "cc `touch should-not-exist`"
    path.write_text(json.dumps(record))
    with pytest.raises(AdapterFactoryError, match="command missing or drift"):
        adapter_artifacts(tmp_path, manifest)
    assert not (tmp_path / "should-not-exist").exists()


@pytest.mark.parametrize("changed", ["patch", "patched", "source", "bitfile"])
def test_legacy_anonymous_patch_and_source_hashes_are_checked(tmp_path, changed):
    manifest, artifact, record_path = fixture(tmp_path)
    manifest.key = "lzss-dipperstein-c"
    paths = {
        "patch": write(
            tmp_path / "adapters/lzss_dipperstein/patches/0001-binary-tree-sentinel-bounds.patch"
        ),
        "patched": write(artifact.parent / "tree.c"),
        "source": write(tmp_path / "adapters/lzss_dipperstein/vendor/lzss/tree.c"),
        "bitfile": write(tmp_path / "adapters/lzss_dipperstein/vendor/lzss/bitfile/bitfile.c"),
    }
    lzss = write(tmp_path / "adapters/lzss_dipperstein/vendor/lzss/lzss.c")
    command_path = artifact.parent / "compile-command.json"
    command = json.loads(command_path.read_text())
    command.update(
        {
            "patch_sha256": digest(paths["patch"]),
            "patched_tree_sha256": digest(paths["patched"]),
            "source_tree_sha256": digest(paths["source"]),
            "unmodified_source_sha256": [
                digest(p) for p in (lzss, paths["source"], paths["bitfile"])
            ],
        }
    )
    command_path.write_text(json.dumps(command))
    record = json.loads(record_path.read_text())
    record["algorithm"] = manifest.key
    record["compile_commands_sha256"] = hashlib.sha256(canonical_json_bytes(command)).hexdigest()
    record_path.write_text(json.dumps(record))
    assert set(paths.values()).issubset(adapter_artifacts(tmp_path, manifest)[1])
    paths[changed].write_bytes(b"changed")
    with pytest.raises(AdapterFactoryError, match="dependency drift"):
        adapter_artifacts(tmp_path, manifest)
