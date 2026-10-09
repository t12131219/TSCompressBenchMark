"""Freeze the complete negotiation universe; keep execution evidence separate."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from verify_all_timing_scopes import select_template

from tscompbench.codecs import CodecRegistry, SourceRegistry, descriptor_from_dataset, negotiate
from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.planning import expand_sweep

ROOT = Path(__file__).resolve().parents[1]


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    source_root = ROOT / "Dataset_Verify/v3"
    index = json.loads((source_root / "index.json").read_text())
    datasets = DatasetRegistry(source_root / "registry", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    points = {}
    for key in codecs:
        _, template = select_template(key)
        points[key] = expand_sweep(
            codecs.get(key), {k: [v[0]] for k, v in template.get("sweep", {}).items()}
        )[0]
    counts = Counter()
    with (output / "universe.jsonl").open("x") as handle:
        for i, entry in enumerate(index["entries"]):
            dataset = load_dataset(datasets.load(entry["key"]))
            for track in BenchmarkTrack:
                descriptor = descriptor_from_dataset(dataset, track)
                for key in codecs:
                    plan = negotiate(codecs.get(key), descriptor, parameters=points[key].parameters)
                    row = {
                        "dataset": entry["key"],
                        "dataset_id": dataset.dataset_id,
                        "algorithm": key,
                        "algorithm_id": codecs.get(key).algorithm_id,
                        "track": track.value,
                        "config_id": points[key].config_id,
                        "compatibility": plan.status.value,
                        "reason": plan.reason_code,
                        "missing": plan.missing_capabilities,
                        "execution_status": "NOT_RUN",
                        "source_domain_checked": False,
                    }
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                    counts[plan.status.value] += 1
            if i % 100 == 0:
                print("planned", i, flush=True)
    result = {
        "status": "PASS",
        "scope": "NEGOTIATION_ONLY_ALL_ROOT_CODECS_ALL_THREE_TRACKS_DEFAULT_TEMPLATE_POINT",
        "dataset_count": len(index["entries"]),
        "codec_count": len(codecs.keys()),
        "counts": dict(counts),
        "task_count": sum(counts.values()),
        "execution_claim": False,
        "source_parity_claim": False,
        "universe_sha256": hashlib.sha256((output / "universe.jsonl").read_bytes()).hexdigest(),
        "aliases": list(codecs.alias_documents()),
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
