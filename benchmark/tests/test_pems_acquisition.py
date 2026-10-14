"""Tiny local streams exercise acquisition integrity; no corpus or real HTTP transfer."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest


SPEC = importlib.util.spec_from_file_location("fetch_pems", Path(__file__).parents[1] / "tools/fetch_pems.py")
fetch_pems = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_pems)


def source(data=b"abcde"):
    return {"id": "pems03", "filename": "PEMS03.npz", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "url": "https://example.test/frozen/PEMS03.npz",
            "author_ref": "fixed-test-ref", "author_blob_url": "https://example.test/blob", "license": "unknown"}


class Response(io.BytesIO):
    status = 200
    url = "https://example.test/frozen/PEMS03.npz"

    def __init__(self, content):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content)), "Content-Type": "application/octet-stream"}
        self.requests = []

    def read(self, size=-1):
        self.requests.append(size)
        return super().read(size)


def response_opener(monkeypatch, response):
    monkeypatch.setattr(fetch_pems.urllib.request, "build_opener",
                        lambda *handlers: SimpleNamespace(open=lambda request, timeout: response))


def fake_catalog(monkeypatch, expected):
    def frozen(path, binding):
        binding.update(preparation_observed_sha256=fetch_pems.PREPARATION_SHA256,
                       preparation_expected_sha256=fetch_pems.PREPARATION_SHA256)
        return {"pems03": expected}
    monkeypatch.setattr(fetch_pems, "frozen_sources", frozen)


def run_args(tmp_path, action="fetch"):
    return [action, "--directory", str(tmp_path / "data"), "--dataset", "pems03",
            "--manifest", str(tmp_path / "ledger.jsonl")]


def events(tmp_path):
    return [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]


def test_actual_preparation_is_pinned_without_reading_npz():
    binding = {}
    frozen = fetch_pems.frozen_sources(fetch_pems.PREPARATION, binding)
    assert set(frozen) == set(fetch_pems.FILENAMES)
    assert frozen["pems03"]["filename"] == "PEMS03.npz"
    assert binding["preparation_observed_sha256"] == fetch_pems.PREPARATION_SHA256
    assert all("9c2e19b98c4cedf1f35214d8789685b6381b3aad" in entry["url"] for entry in frozen.values())


def test_success_installs_exact_bytes_atomically(monkeypatch, tmp_path):
    expected = source()
    fake_catalog(monkeypatch, expected)
    response_opener(monkeypatch, Response(b"abcde"))
    assert fetch_pems.main(run_args(tmp_path)) == 0
    assert (tmp_path / "data/PEMS03.npz").read_bytes() == b"abcde"
    assert not list((tmp_path / "data").glob(".pems-*"))
    log = events(tmp_path)
    terminal = next(row for row in log if row["event"] == "source_finished")
    assert terminal["expected_sha256"] == expected["sha256"] == terminal["streamed_sha256"]
    assert terminal["download_installed"] and terminal["byte_identity_verified"]
    assert terminal["status"] == "ok" and log[-1]["status"] == "complete"
    assert [row["sequence"] for row in log] == list(range(len(log)))


@pytest.mark.parametrize("body,reason,observed", [
    (b"abcd", "shorter", 4), (b"abcdf", "SHA-256", 5), (b"abcdef" * 100, "exceeds", 6),
])
def test_invalid_body_records_rejection_and_never_installs(monkeypatch, tmp_path, body, reason, observed):
    expected = source()
    fake_catalog(monkeypatch, expected)
    response = Response(body)
    response_opener(monkeypatch, response)
    assert fetch_pems.main(run_args(tmp_path)) == 1
    assert not (tmp_path / "data/PEMS03.npz").exists()
    assert not list((tmp_path / "data").glob(".pems-*"))
    row = next(row for row in events(tmp_path) if row["event"] == "source_finished")
    assert row["status"] == "error" and reason in row["reason"]
    assert row["expected_bytes"] == 5 and row["expected_sha256"] == expected["sha256"]
    assert row["streamed_bytes"] == observed and row["streamed_sha256"] == hashlib.sha256(body[:observed]).hexdigest()
    assert not row["download_installed"] and not row["byte_identity_verified"]
    assert all(0 < size <= 6 for size in response.requests)


def test_network_interruption_retains_partial_observation(monkeypatch, tmp_path):
    class BrokenResponse(Response):
        def read(self, size=-1):
            if self.tell():
                raise OSError("network interrupted after two bytes")
            return super().read(2)
    expected = source()
    fake_catalog(monkeypatch, expected)
    response_opener(monkeypatch, BrokenResponse(b"abcde"))
    assert fetch_pems.main(run_args(tmp_path)) == 1
    row = next(row for row in events(tmp_path) if row["event"] == "source_finished")
    assert row["streamed_bytes"] == 2 and row["streamed_sha256"] == hashlib.sha256(b"ab").hexdigest()
    assert row["error_type"] == "OSError" and row["http_status"] == 200
    assert row["expected_sha256"] == expected["sha256"] and not row["download_installed"]
    assert not (tmp_path / "data/PEMS03.npz").exists()


def test_http_error_is_evidence_not_source_bytes(monkeypatch, tmp_path):
    expected = source()
    fake_catalog(monkeypatch, expected)
    def fail(request, timeout):
        raise urllib.error.HTTPError(expected["url"], 403, "Forbidden", {}, io.BytesIO(b"access denied"))
    monkeypatch.setattr(fetch_pems.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=fail))
    assert fetch_pems.main(run_args(tmp_path)) == 1
    row = next(row for row in events(tmp_path) if row["event"] == "source_finished")
    assert row["http_status"] == 403 and row["response_body_prefix"] == "access denied"
    assert row["streamed_bytes"] == 0 and row["expected_sha256"] == expected["sha256"]
    assert not row["download_installed"]


def test_install_collision_preserves_other_writer(monkeypatch, tmp_path):
    response_opener(monkeypatch, Response(b"abcde"))
    link = fetch_pems.os.link
    path = tmp_path / "PEMS03.npz"
    def collide(temporary, target, **options):
        target.write_bytes(b"other writer")
        return link(temporary, target, **options)
    monkeypatch.setattr(fetch_pems.os, "link", collide)
    record = {}
    with pytest.raises(FileExistsError):
        fetch_pems.fetch_exact(path, source(), record, 5)
    assert path.read_bytes() == b"other writer"
    assert record["byte_identity_verified"] and not record["download_installed"]
    assert not list(tmp_path.glob(".pems-*"))


def test_polluted_existing_file_is_not_refetched_or_overwritten(monkeypatch, tmp_path):
    expected = source()
    fake_catalog(monkeypatch, expected)
    (tmp_path / "data").mkdir()
    path = tmp_path / "data/PEMS03.npz"
    path.write_bytes(b"abcdf")
    monkeypatch.setattr(fetch_pems.urllib.request, "build_opener",
                        lambda *handlers: pytest.fail("existing data must not be refetched"))
    assert fetch_pems.main(run_args(tmp_path)) == 1
    assert path.read_bytes() == b"abcdf"
    row = next(row for row in events(tmp_path) if row["event"] == "source_finished")
    assert row["stage"] == "verify_existing" and not row["download_installed"]
    assert row["expected_sha256"] == expected["sha256"]


def test_verify_existing_matches_exact_bytes_without_parse(tmp_path):
    path = tmp_path / "PEMS03.npz"
    path.write_bytes(b"abcde")
    record = {}
    fetch_pems.verify_existing(path, source(), record)
    assert record["byte_identity_verified"] and record["streamed_bytes"] == 5
    assert "no NPZ parsing" in record["verification_scope"]


@pytest.mark.parametrize("mutation", ["replace", "in_place"])
def test_existing_source_changed_during_read_is_rejected(monkeypatch, tmp_path, mutation):
    path = tmp_path / "PEMS03.npz"
    path.write_bytes(b"abcde")
    original_read = fetch_pems.bounded_identity
    def change_after_valid_read(stream, expected, record, **options):
        original_read(stream, expected, record, **options)
        if mutation == "replace":
            path.unlink()
            path.write_bytes(b"evilx")
        else:
            before = path.stat()
            path.write_bytes(b"evilx")
            fetch_pems.os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))
    monkeypatch.setattr(fetch_pems, "bounded_identity", change_after_valid_read)
    record = {}
    with pytest.raises(ValueError, match="changed during verification"):
        fetch_pems.verify_existing(path, source(), record)
    assert path.read_bytes() == b"evilx"
    assert record["streamed_sha256"] == source()["sha256"]
    assert not record["byte_identity_verified"] and not record["path_identity_verified"]
    assert record["file_stat_before_read"] != record["path_stat_after_read"]


def test_dangling_symlink_is_rejected_without_fetch(monkeypatch, tmp_path):
    fake_catalog(monkeypatch, source())
    (tmp_path / "data").mkdir()
    path = tmp_path / "data/PEMS03.npz"
    path.symlink_to(tmp_path / "missing")
    monkeypatch.setattr(fetch_pems.urllib.request, "build_opener",
                        lambda *handlers: pytest.fail("a dangling symlink occupies the destination"))
    assert fetch_pems.main(run_args(tmp_path)) == 1
    assert path.is_symlink()
    assert "regular file" in next(row for row in events(tmp_path) if row["event"] == "source_finished")["reason"]


def test_ledger_cannot_be_overwritten(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = fetch_pems.Ledger(path)
    ledger.append("first", value="original")
    ledger.close()
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        fetch_pems.Ledger(path)
    assert path.read_bytes() == before
    with pytest.raises(SystemExit) as error:
        fetch_pems.main(run_args(tmp_path))
    assert error.value.code == 2 and path.read_bytes() == before


def test_polluted_preparation_is_rejected_with_fresh_ledger(tmp_path):
    bad = tmp_path / "bad-preparation.json"
    bad.write_text("{}")
    assert fetch_pems.main(run_args(tmp_path) + ["--preparation", str(bad)]) == 1
    row = next(row for row in events(tmp_path) if row["event"] == "preparation_rejected")
    assert row["preparation_expected_sha256"] == fetch_pems.PREPARATION_SHA256
    assert row["preparation_observed_sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert events(tmp_path)[-1]["status"] == "failed" and not (tmp_path / "data").exists()


def test_https_redirect_downgrade_is_rejected():
    with pytest.raises(ValueError, match="outside HTTPS"):
        fetch_pems.HTTPSRedirect().redirect_request(None, None, 302, "Found", {}, "http://example.test/bytes")


def test_manifest_cannot_occupy_data_filename(tmp_path):
    args = run_args(tmp_path)
    args[args.index("--manifest") + 1] = str(tmp_path / "data/PEMS03.npz")
    with pytest.raises(SystemExit) as error:
        fetch_pems.main(args)
    assert error.value.code == 2 and not (tmp_path / "data").exists()
