"""Apply a user-requested DeepZip exclusion to a frozen forecasting design."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'benchmark/tools'))
from generate_all_core_experiments import text as toml_text
import tomllib


def main() -> None:
    design_path = Path(sys.argv[1]).resolve()
    design = json.loads(design_path.read_text())
    previous_skip_amendment = design.get('user_skip_amendment')
    amendment_dir = design_path.parent / 'amendments/skip-deepzip'
    amendment_dir.mkdir(parents=True, exist_ok=True)
    backup = amendment_dir / 'design.before.json'
    if not backup.exists():
        shutil.copy2(design_path, backup)

    removed_requests = 0
    rewritten = []
    retained = []
    for entry in design['configurations']:
        if 'deepzip' not in entry['codecs']:
            retained.append(entry)
            continue
        deepzip_cases = len(entry['input_ids'])
        removed_requests += deepzip_cases
        if entry['codecs'] == ['deepzip']:
            rewritten.append({'path': entry['path'], 'run': entry['run'],
                              'action': 'removed_deepzip_only_configuration',
                              'preserved_run_directory': Path(entry['run']).exists()})
            continue

        run_dir = Path(entry['run'])
        summary = run_dir / 'report/summary.json'
        manifest = run_dir / 'manifest.json'
        complete = (summary.exists() and manifest.exists() and
                    json.loads(manifest.read_text()).get('state') == 'complete')
        if complete:
            entry['analysis_excluded_codecs'] = sorted(set(entry.get('analysis_excluded_codecs', [])) | {'deepzip'})
            entry['requests'] -= deepzip_cases
            entry['codecs'] = [key for key in entry['codecs'] if key != 'deepzip']
            retained.append(entry)
            rewritten.append({'path': entry['path'], 'run': entry['run'],
                              'action': 'preserved_completed_run_filtered_in_analysis',
                              'excluded_requests': deepzip_cases})
            continue

        source = Path(entry['path'])
        config = tomllib.loads(source.read_text())
        config['methods'] = [method for method in config['methods']
                             if method.get('codec', method.get('id')) != 'deepzip']
        new_path = source.with_name(source.stem + '-no-deepzip' + source.suffix)
        new_run = Path(entry['run']).with_name(Path(entry['run']).name + '-no-deepzip')
        config['name'] = new_path.stem
        config['output'] = str(new_run)
        new_text = toml_text(config)
        if new_path.exists() and new_path.read_text() != new_text:
            raise FileExistsError(f'revised config differs: {new_path}')
        new_path.write_text(new_text)
        entry.update({'path': str(new_path), 'run': str(new_run),
                      'sha256': 'sha256:' + hashlib.sha256(new_path.read_bytes()).hexdigest(),
                      'requests': entry['requests'] - deepzip_cases,
                      'codecs': [key for key in entry['codecs'] if key != 'deepzip']})
        retained.append(entry)
        rewritten.append({'path': str(new_path), 'run': str(new_run),
                          'action': 'replaced_incomplete_configuration',
                          'preserved_previous_config': str(source),
                          'preserved_previous_run_directory': str(run_dir),
                          'excluded_requests': deepzip_cases})

    design['configurations'] = retained
    design['codecs'] = [key for key in design['codecs'] if key != 'deepzip']
    design['user_skipped_codecs'] = sorted(set(design.get('user_skipped_codecs', [])) | {'deepzip'})
    design['requested_cases'] -= removed_requests
    design['user_skip_amendment'] = 'benchmark/experiments/' + design_path.parent.name + '/amendments/skip-deepzip/amendment.json'
    design['created_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    amendment = {'schema': 'tsbench.user-skip-amendment/1',
                 'created_at': design['created_at'], 'reason': 'User explicitly excluded DeepZip.',
                 'skipped_codec': 'deepzip', 'excluded_requests': removed_requests,
                 'configurations_before': len(rewritten) + len(retained),
                 'configurations_after': len(retained), 'rewritten_or_preserved': rewritten,
                 'previous_dzip_amendment': previous_skip_amendment}
    (amendment_dir / 'amendment.json').write_text(json.dumps(amendment, ensure_ascii=False, indent=2) + '\n')
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'configurations': len(retained), 'codecs': len(design['codecs']),
                      'requested_cases': design['requested_cases'],
                      'excluded_deepzip_requests': removed_requests}, ensure_ascii=False))


if __name__ == '__main__':
    main()
