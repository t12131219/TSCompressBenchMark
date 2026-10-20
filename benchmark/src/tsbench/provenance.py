"""Named source identities for the execution and measurement protocol."""
from __future__ import annotations

from pathlib import Path

from .records import file_hash, stable_hash


def execution_files(package: Path | None = None) -> list[Path]:
    package = package or Path(__file__).resolve().parent
    names = ("__init__.py", "__main__.py", "cli.py", "config.py", "runner.py", "records.py",
             "worker.py", "artifact.py", "schemes.py", "validate.py", "data.py", "registry.py",
             "errors.py", "executors/cpu.py", "runtime.py", "transforms.py", "provenance.py",
             "quality_metadata.py", "native.py")
    return [path for path in [*(package / name for name in names),
                              *sorted((package / "bridges").rglob("*.py"))] if path.is_file()]


def execution_provenance(package: Path | None = None) -> dict:
    package = package or Path(__file__).resolve().parent
    sources = [{"path": str(path.resolve()), "module": str(path.relative_to(package)),
                "sha256": file_hash(path)} for path in execution_files(package)]
    native=package.parents[1]/'native'
    sources.extend({'path':str(path.resolve()),'module':'native/'+path.name,'sha256':file_hash(path)}
                   for path in sorted(native.glob('*')) if path.suffix in {'.cpp','.hpp'})
    return {"schema": "tsbench.execution-provenance/1", "source_id": stable_hash(sources),
            "sources": sources,
            "scope": "named Python runner/measurement/codec bridge closure; native toolchain, source, binary, model and runtime identities are in each case's build_evidence/implementation_id",
            "analysis_policy": "report/study/trial_analysis/plot code does not revoke measurement qualification; its hashes are recorded by the analyses"}


def snapshot_sources(destination: Path, package: Path | None = None) -> dict:
    """Save reviewable source bytes before admission, without overwriting history."""
    package = package or Path(__file__).resolve().parent
    destination.mkdir(parents=True, exist_ok=False)
    copied = []
    for source in sorted(package.rglob("*.py")):
        target = destination / source.relative_to(package)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        source_hash = file_hash(source)
        if file_hash(target) != source_hash:
            raise RuntimeError("source changed during snapshot; start a new run")
        copied.append({"module": str(source.relative_to(package)), "path": str(target.resolve()),
                       "sha256": source_hash})
    for source in sorted((package.parents[1]/'native').glob('*')):
        if source.suffix not in {'.cpp','.hpp'}:continue
        target=destination.parent/'native'/source.name
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise FileExistsError(target)
        target.write_bytes(source.read_bytes())
        if file_hash(target)!=file_hash(source):raise RuntimeError('native source changed during snapshot')
        copied.append({'module':'native/'+source.name,'path':str(target.resolve()),'sha256':file_hash(source)})
    return {"path": str(destination.resolve()), "files": copied, "snapshot_id": stable_hash(copied),
            "scope": "entire Python package before admission, including execution, analysis and build recipes; each executed native binary/source closure is separately recorded by build evidence"}
