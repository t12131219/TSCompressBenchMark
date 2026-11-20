#!/usr/bin/env python3
"""Write per-file metric JSONL and a coverage summary from one sealed M3 ledger."""
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_metric_details import extract
from tsbench.application.smoke import write_new
from tsbench.assets import digest, load_json, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'run', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    a = p.parse_args()
    target = a.out.resolve()
    require(target.parent.is_dir() and not target.exists(), 'metric output must be a new directory under an existing directory')
    with TemporaryDirectory(dir=target.parent, prefix='.metric-') as tmp:
        staged = Path(tmp) / 'data'
        staged.mkdir()
        details = staged / 'decisions.jsonl'
        with details.open('xb') as output:
            facts = extract(load_json(a.plan), a.run.resolve(strict=True), output)
        code = ('src/tsbench/application/m3_metric_details.py', 'tools/m3_metric_details.py')
        write_new(staged / 'summary.json', {**facts, 'normalizer_sha256': {p: digest(ROOT / p) for p in code},
                                            'detail': {'path': details.name, 'sha256': digest(details), 'bytes': details.stat().st_size}})
        require(not target.exists(), 'metric output appeared during extraction')
        staged.rename(target)


if __name__ == '__main__':
    main()
