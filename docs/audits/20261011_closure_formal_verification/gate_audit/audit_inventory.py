#!/usr/bin/env python3
"""Read-only gate satisfiability inventory; never executes codecs or tests."""
from __future__ import annotations

import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import yaml

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
AUTH = Path('/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos')
ARCHIVE = ROOT / 'docs/rewrite_cleanup/20261006-integration/historical_metadata.tar.gz'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def ref(path: Path) -> dict:
    return {'path': str(path), 'exists': path.is_file(),
            **({'sha256': sha(path), 'bytes': path.stat().st_size} if path.is_file() else {})}


def save(name: str, data) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def walk_files(root: Path, errors: list):
    if not root.exists():
        return
    def onerror(error):
        errors.append({'path': error.filename, 'error': str(error)})
    for base, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules'}]
        for name in files:
            yield Path(base) / name


def environment_inventory(tar: tarfile.TarFile) -> dict:
    lock = json.loads(tar.extractfile('Source/deepzip/ORACLE_ENVIRONMENT_LOCK.json').read())
    dzip_lock = yaml.safe_load(tar.extractfile('Source/dzip/TOOLCHAIN_MANIFEST.yaml').read())
    expected = []
    for kind in ('conda', 'pip_acquisition_archives'):
        for x in lock[kind]:
            expected.append({'recipe': 'deepzip', 'kind': kind, 'filename': x['filename'],
                             'sha256': x['sha256'], 'bytes': x['size_bytes']})
    for x in dzip_lock['overlay_archives']:
        expected.append({'recipe': 'dzip_overlay', 'kind': 'pip', 'filename': x['filename'],
                         'sha256': x['sha256'], 'bytes': x['bytes']})
    filenames = {x['filename'] for x in expected}
    sizes = {x['bytes'] for x in expected}
    search_roots = [Path('/home/fzg/anaconda3/pkgs'), Path('/home/fzg/.cache/pip'),
                    Path('/home/fzg/PycharmProjects/Compression_Rewrite'),
                    Path('/home/fzg/PycharmProjects/Compression_Source_Code'),
                    Path('/home/fzg/PycharmProjects/材料'),
                    Path('/tmp/tscb-legacy-conda-pkgs'), Path('/tmp/tscb-deepzip-wheelhouse'),
                    Path('/tmp/tscb-dzip-wheels')]
    errors, candidates = [], []
    for root in search_roots:
        for p in walk_files(root, errors):
            try:
                n = p.stat().st_size
                # Match opaque pip-cache payloads by size as well as explicit filenames.
                if p.name in filenames or (root == Path('/home/fzg/.cache/pip') and n in sizes):
                    candidates.append(ref(p))
            except OSError as e:
                errors.append({'path': str(p), 'error': str(e)})
    for x in expected:
        x['matching_local_bytes'] = [r['path'] for r in candidates if r['sha256'] == x['sha256']]
        x['same_filename_candidates'] = [r for r in candidates if Path(r['path']).name == x['filename']]
        x['availability'] = 'HASH_MATCHED_LOCAL_ARCHIVE' if x['matching_local_bytes'] else 'NOT_FOUND_IN_SEARCHED_ROOTS'
    prefixes = [Path('/home/fzg/anaconda3')]
    prefixes += sorted(p for p in Path('/home/fzg/anaconda3/envs').iterdir() if p.is_dir())
    envs = []
    for p in prefixes:
        packages = []
        for m in sorted((p / 'conda-meta').glob('*.json')):
            d = json.loads(m.read_text())
            if d.get('name') in {'python', 'tensorflow', 'tensorflow-gpu', 'keras', 'numpy', 'cudnn', 'cudatoolkit'}:
                packages.append({k: d.get(k) for k in ('name', 'version', 'build')})
        envs.append({'prefix': str(p), 'conda_packages': packages,
                     'tensorflow_dirs': [str(x) for x in p.glob('lib/python*/site-packages/tensorflow*')],
                     'keras_dirs': [str(x) for x in p.glob('lib/python*/site-packages/keras*')]})
    executables = [Path(lock['executable']), Path('/tmp/tscb-deepzip-oracle-rebuilt/bin/python'),
                   Path(dzip_lock['executable'])]
    gpu_cmd = ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader']
    proc = subprocess.run(gpu_cmd, capture_output=True, text=True, timeout=15)
    return {'search_roots': [{'path': str(p), 'exists': p.exists()} for p in search_roots],
            'search_errors': errors, 'acquisition_archives': expected,
            'archive_availability_counts': dict(collections.Counter(x['availability'] for x in expected)),
            'conda_prefixes': envs, 'locked_executables': [ref(p) for p in executables],
            'gpu_probe': {'command': gpu_cmd, 'exit_code': proc.returncode,
                          'stdout': proc.stdout, 'stderr': proc.stderr,
                          'device_nodes': [str(p) for p in Path('/dev').glob('nvidia*')],
                          'nvcc_path': shutil.which('nvcc'),
                          'interpretation': 'Current process cannot communicate with NVIDIA driver. This alone does not establish absence of host hardware or authorize waiving REQUIRED_PARITY.'},
            'offline_exact_runtime_rebuild': 'NOT_AVAILABLE_FROM_OBSERVED_LOCAL_ASSETS',
            'source_runtime_executed': False,
            'installed_or_downloaded_packages': False}


def capability_inventory(tar: tarfile.TarFile) -> list:
    names = set(tar.getnames())
    result = []
    for key in ('abba', 'fabba', 'deepzip', 'dzip'):
        p = ROOT / f'adapters/completed_rewrites/vendor/{key}/NATIVE_CAPABILITY_MATRIX.yaml'
        d = yaml.safe_load(p.read_text())
        rows = []
        for c in d['capabilities']:
            validation = c.get('validation', {})
            tests = list(validation.get('tests', []))
            paths = [x for x in tests if '/' in x or Path(x).suffix]
            paths += [x['path'] for x in validation.get('artifacts', [])]
            rows.append({'capability_id': c['capability_id'], 'parity_class': c['parity_class'],
                         'historical_recorded_validation': validation.get('status'),
                         'test_case_labels': [x for x in tests if x not in paths],
                         'upstream': c.get('upstream'), 'rewrite': c.get('rewrite'),
                         'evidence_paths': [{'path': x,
                                             'current_vendor_file_exists': (p.parent / x).is_file(),
                                             'archive_metadata_exists': f'ReWrite/{key}/{x}' in names}
                                            for x in paths],
                         'current_gate_status': 'NOT_REGRANTED_BY_THIS_STATIC_INVENTORY'})
        result.append({'codec': key, 'matrix': ref(p), 'historical_overall_result': d.get('overall_result'),
                       'class_counts': dict(collections.Counter(c['parity_class'] for c in rows)),
                       'non_v3_classes': [c['capability_id'] for c in rows if c['parity_class'] not in
                                          {'REQUIRED_PARITY', 'OPTIONAL_OPTIMIZATION', 'UNAVAILABLE_WITH_WAIVER', 'NOT_APPLICABLE'}],
                       'capabilities': rows,
                       'interpretation': 'Saved claims and archived metadata are historical evidence availability; neither is a current fresh CAP-GATE execution.'})
    return result


def source_inventory() -> dict:
    trained = sorted((AUTH / 'mohit1997_DeepZip/data/trained_models').rglob('*.hdf5'))
    dzip_models = sorted((AUTH / 'mohit1997_DZip').rglob('*.hdf5'))
    all_models = [ref(p) for p in trained + dzip_models]
    errors, copies = [], []
    roots = [Path('/home/fzg/PycharmProjects/Compression_Source_Code'),
             Path('/home/fzg/PycharmProjects/Compression_Rewrite'), Path('/home/fzg/PycharmProjects/材料')]
    wanted = {'lzss.c', 'lzss.h', 'tree.c', 'bitfile.c', 'bitfile.h'}
    for root in roots:
        for p in walk_files(root, errors):
            if p.name in wanted and ('lzss' in str(p).lower() or 'bitfile' in str(p).lower()):
                copies.append(ref(p))
    vendor = ROOT / 'adapters/lzss_dipperstein/vendor/lzss'
    vendor_files = [ref(p) for p in sorted(vendor.rglob('*')) if p.is_file()]
    return {'authority_root': str(AUTH),
            'learned_source_files': [ref(AUTH / repo / p) for repo, paths in {
                'mohit1997_DeepZip': ['README.md','src/models.py','src/compressor.py','src/decompressor.py','src/trainer.py'],
                'mohit1997_DZip': ['README.md','encode-decode/models.py','encode-decode/compressor.py',
                                  'encode-decode/decompressor.py','encode-decode/train_bootstrap.py']}.items() for p in paths],
            'trained_hdf5_files': all_models, 'trained_hdf5_count': len(all_models),
            'deepzip_trained_hdf5_count': len(trained), 'dzip_trained_hdf5_count': len(dzip_models),
            'dipperstein_search_roots': [str(p) for p in roots], 'search_errors': errors,
            'dipperstein_related_external_files': copies, 'current_vendor_files': vendor_files,
            'dipperstein_original_authority_status': 'NO_INDEPENDENT_ORIGINAL_LZSS_AUTHORITY_FOUND_IN_SEARCHED_ROOTS',
            'note': 'Current vendored files and derived copies do not independently verify pinned original upstream commits.'}


CUSTOM = {
 'abba': 'Freeze full Python/CKmeans source call graph, norm/scl/max_len and clustering/tie parameters; distinguish stage-composed oracle from complete unmodified Python pipeline. Replay all required canonical/alternate profiles on identical real inputs, including repaired length bounds; release current package independently.',
 'fabba': 'Preserve stable-norm2-scl1-v1 as an explicit variant; freeze unmodified source AGG versus stabilized digitization scopes. Validate required partitioned parallel API, real requested/actual thread paths and race/state isolation; replay current length fixes, full dataset plan and standalone release.',
 'deepzip': 'Restore exact Python3.6.13/TF-GPU1.8/Keras2.2.2/NumPy1.16.4/CUDA9/cuDNN7.1.2 reference environment. Fresh-execute all 17 reachable constructors and original checkpoint loading, whole arithmetic pipeline, trained checkpoint and CUDA paths with independent input/model hashes; test native HDF5/CUDA API, preserve CPU four-symbol fixture profile as a subset.',
 'dzip': 'Restore exact Python3.6.13/TF-CPU1.14/Keras2.2.2/NumPy1.16.4 reference. Fresh source initializer/imported PRNN, bootstrap training, full batch/tail and online Adam weight/state/CDF trajectory must be compared to corresponding C++ paths; seeded/untrained native variant is not source parity. Separately execute official CUDA bootstrap training, HDF5/BSC checkpoint restoration and standalone public training API.',
 'lzss-raw': 'Freeze full alexkazik public generic/dynamic/in-place API inventory beyond EI10/EJ4/C32; fresh raw/cross-decode current fixed-profile baseline exists. Prove complete required parameter/state APIs separately; test current independent core/header and dataset differential in standalone release, without Bench dependency.',
 'lzss-dipperstein-c': 'Obtain independently attributable original lzss commit65b6882 and bitfile commit2e6132 source closure; existing vendor may support tests but is not independent authority. Replay sentinel patch against original and compare affected legal raw streams, rejection/token boundaries, file API state and independent cold recovery.',
 'neats-lossless-i64': 'Use locked original C++ baseline and replay the three current patches; compare scalar/predictor/frame/index behavior explicitly as modified variant. Test signed min-shift extremes, serialization, query/range/column and lifecycle independently; keep original SIMD inventory separate from opened scalar profile.',
 'leats-lossless-i64': 'As NeaTS shared closure, plus LeaTS binary64 predictor and serialization impact against the original baseline; signed normalization/extremes and fresh query/index frame evidence must be specific to LeaTS.',
 'alp': 'Replay three safety patches against ALP/FastLanes baseline; compare legal decimal ALP decisions/bytes/exception values, enforced ALP rejection where upstream chooses RD, f32/f64 rowgroup/tail and required opened ISA. Independent RAW composition must remain separate.',
 'alp-rd': 'Shared ALP/FastLanes source and patches; independently compare forced RD dictionary/exception path, f32/f64 rowgroup/tail and actual ISA, preserving source adaptive selection inventory.',
 'serf-qt': 'Replay three build-copy safety patches; compare Qt numeric/reconstruction behavior and total original-domain error on real data, exception RAW records, tails and malformed streams. Independent RAW fallback must not count as source Qt coding.',
 'serf-xor': 'Replay shared Serf patches but compare XOR branch independently; exact error, overflow/IEEE RAW, tail/state and bitstream/semantic target remain branch-specific.',
 'simdcomp-u32': 'Use original C SSE4.1/AVX2 primitive baseline; replay four patches and validate each promised plain u32 API/ISA, widths0..32, alignment/padding, capacity and tails. Preserve P0 length/type protocol, do not grant delta/FOR/FastPFOR capabilities.',
 'sprintz-delta': 'Replay safety/overflow staging patches against original delta path; same canonical signed/unsigned8/16-bit matrices, dimensions/group and tails. Verify AVX2/BMI2/LZCNT actually executed, allocation failure and affected bytes/state.',
 'sprintz-delta-u8': 'Validate original low-dimensional uint8 delta path specifically; original-versus-patched staging/guard/tail, AVX2/BMI2/LZCNT and capacity do not borrow broad16-bit evidence.',
 'sprintz-fire': 'Replay FIRE predictor overflow and allocation safety against original; compare legal predictor/state and final bytes on same8/16-bit matrices, group dimensions/tail and forced actual AVX2/BMI2/LZCNT.',
 'sprintz-fire-u8': 'Validate low-dimensional uint8 FIRE independently; same original predictor inputs, legal overflow semantics, guard/staging/tail and actual ISA; no grant to full16-bit profile.',
 'sprintz-fire-huff0': 'Validate independent P2 FIRE→HUF stage boundaries and inverse stages; current complete frame and both costs, HUF entropy/RAW branches, original FIRE and HUF separate oracles, actual ISA and tails.',
 'chimp': 'Fresh source Chimp/Chimp32 raw equality and cross-decode currently available. Complete Java public API/format/source-domain inventory, required state/path dataset plan and independent current core/API release; Bench RWF1/FFI remains separate.',
 'chimp128': 'Fresh source ChimpN/ChimpN32 N128 evidence exists; full required N/parameter and public state APIs require separate inventory/coverage. Release and dataset gates must bind current core/API, not shared package labels.',
 'elf': 'Fresh Java raw/cross-decode exists. Preserve END/significance/scale/source rejection and actual license-decision scope; full public API/required capabilities and current independent package/API/security/dataset/release gates remain to sign.',
 'elf-plus': '82 fresh legal raw/cross-decode cases and2 fresh END cases exist;8 failures are archive-expected bounded native rejection, not fresh original failure. Freeze source legal/domain defects and finish standalone API/dataset/release/CAP gates with independent expected data.',
 'elf-star': 'Fresh Java algorithm path uses documented helper compile overlay; retain exact source/path versus overlay identity. Complete required public capabilities, state/dataset/current standalone release; do not call patched Java build entirely unmodified.',
 'self-star': 'Fresh raw/cross-decode plus6 standalone network cases exist. Freeze full required network/shared-state API and compare reset/block/seek/stream semantics directly; Bench unopened network capability is separate; complete independent release gates.',
 'deflate-zlib': 'Run locked upstream/independent zlib API baseline and current wrapper contract for RFC1950 complete stream; include flush/Finalize/reset/backpressure/capacity and dictionaries only if current frozen scope includes them, with raw DEFLATE separately inventoried.',
 'lz4-frame': 'Current output.used/EOF/reset safety tests and legal byte/cross-decode baseline exist. Preserve complete LZ4 frame comparison object, replay binding patch and independent source frame API real-data/lifecycle/cold recovery; raw lzbench block is a different object.',
 'zstd-frame': 'Current output.used/EOF/reset tests and legal byte/cross-decode baseline exist. Preserve complete Zstd frame, single-thread no-dict opened scope versus source broader dictionary/MT inventory; independent API baseline, memory/state and current runtime closure.',
 'brotli-stream': 'Run original Brotli stream API tests/independent baseline and complete wrapper stream reset/finalize/backpressure/capacity/malformed/cold recovery on real byte views. Built-in versus external dictionary policy and source broader params remain explicit.',
 'xz-stream': 'Run original liblzma XZ/LZMA2 API baseline and current preset6/checkNONE stream lifecycle, structure CRC, tails/malformed/cold recovery; do not grant rawLZMA/all filters/multithreading outside current scope.',
 'snappy-raw': 'Run original Snappy raw public API/independent baseline on same complete raw objects, capacity/expanded inputs/malformed/cold typed recovery; no framed stream/dictionary/checksum grant.',
 'zfp-accuracy-1d': 'Run original serial fixed-accuracy1D API baseline on identical f32/f64 real columns, actual tolerance/full header/tails and original-domain error. IEEE exception RAW must be reported separately; no rate/precision/reversible/ND/CUDA outside scope.',
 'huff0': 'Run original HUF API baseline and current complete RAW/RLE/HUF frame, capacity expansion/incompressible/empty/tails/typed cold recovery; distinguish source entropy bytes from project frame and literal RAW.',
 'fse': 'Run original FSE API baseline and current complete RAW/RLE/FSE frame, capacity/errors/malformed/typed cold recovery; distinguish source entropy bytes and project frame/cost.',
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    consumed = [ROOT / 'Compression_Algorithm_CPP_Porting_Standard_v3.0.md',
                ROOT / 'docs/audits/20261011_porting_standard/rewrite_routes.json',
                ROOT / 'docs/audits/20261011_porting_standard/learned_oracle_availability.json',
                ROOT / 'docs/audits/20261011_porting_standard/source_build_inventory_r1/inventory-final-r2.json',
                ROOT / 'docs/audits/20261011_porting_standard/final_evidence_index.json', ARCHIVE]
    before = [ref(p) for p in consumed]
    with tarfile.open(ARCHIVE) as tar:
        env = environment_inventory(tar)
        cap = capability_inventory(tar)
        archive_meta = {'archive': ref(ARCHIVE), 'member_count': len(tar.getnames()),
                        'package_payload_members': [n for n in tar.getnames() if n.endswith(('.whl', '.conda', '.tar.bz2'))]}
        for name in ('Source/deepzip/ENVIRONMENT.md', 'Source/dzip/TOOLCHAIN_MANIFEST.yaml'):
            b = tar.extractfile(name).read()
            (OUT / ('archived-' + name.replace('/', '__'))).write_bytes(b)
    src = source_inventory()
    routes = json.loads(consumed[1].read_text())['entries']
    inventory = {r['codec_key']: r for r in json.loads(consumed[3].read_text())['rows']}
    entries = []
    for r in routes:
        key = r['codec']; inv = inventory[key]; native = r['implementation_route'] != 'SOURCE_REWRITE'
        entries.append({'codec_key': key, 'route': r['implementation_route'], 'gate_family': 'N0-N5' if native else 'G0-G6/CAP',
                        'object_level': r['object_level'], 'registered_profile': r['registered_profile_scope'],
                        'already_saved_scoped_evidence': r['current_source_or_core_evidence'],
                        'current_declared_execution_dependency_status': inv['registered_execution_dependencies'].get('status'),
                        'source_inventory_status': inv['source_inventory']['closure_status'],
                        'source_closure_status_is_not_automatically_n1_failure': True,
                        'complete_gate_decision': 'NOT_GRANTED_AUDIT_AND_EXECUTION_STILL_REQUIRED',
                        'entry_specific_action': CUSTOM[key],
                        'common_required_actions': [
                            'Freeze source public/API/build/docs/tests/CI capability universe and current target separately; classify every required capability, with reviewed owner/platform/test/provenance.',
                            'Complete actual source/generated/compiler/linker/static-startup/runtime/model trace and immutable per-file hashes; replay every patch and keep original/patched source separately.',
                            'Map original public API/driver, boundary/malformed/ownership/lifecycle/concurrency and real datasets to each promised scope; recorded successful finite tests do not cover unexecuted domains.',
                            'Validate independent source/API/driver packaging and cold rebuild/recovery without Bench runtime/registry; complete SBOM/license/report index with exact consumed bytes.',
                        ] + ([] if native else ['Complete all G0-G6 and CAP checkpoints, canonical/required optimized dataset differential and independent current release qualification.']),
                        'complete_gate_remaining_boundary': r['limitations'],
                        'external_blockers': (['EXACT_REFERENCE_RUNTIME_NOT_LOCAL', 'CURRENT_GPU_DRIVER_COMMUNICATION_UNAVAILABLE'] if key == 'deepzip' else
                                              ['EXACT_REFERENCE_RUNTIME_NOT_LOCAL', 'CURRENT_CUDA_BOOTSTRAP_DEVICE_EXECUTION_UNAVAILABLE'] if key == 'dzip' else
                                              ['NO_INDEPENDENT_PINNED_ORIGINAL_AUTHORITY_IN_SEARCHED_ROOTS'] if key == 'lzss-dipperstein-c' else []),
                        'formal_relationship': 'N5 does not require FORMAL; current declared-profile FORMAL may be tested separately. Never label it upstream FULL_PARITY or independent REWRITE_DONE.'})
    after = [ref(p) for p in consumed]
    save('environment_inventory.json', env)
    save('source_assets.json', src)
    save('capability_inventory.json', cap)
    save('report.json', {'schema_version': 'tscb.independent-gate-satisfiability-audit.v1',
                         'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         'status': 'READ_ONLY_SATISFIABILITY_INVENTORY_COMPLETE_NO_GATES_REGRANTED',
                         'input_snapshots_unchanged': before == after, 'input_snapshot': before,
                         'inventory_driver': ref(Path(__file__).resolve()),
                         'inventory_python': ref(Path(sys.executable).resolve()),
                         'archive_metadata': archive_meta, 'active_entry_count': len(entries),
                         'route_counts': dict(collections.Counter(r['route'] for r in entries)),
                         'source_runtime_executed': False, 'codec_or_tests_executed': False,
                         'new_formal_performance_executed': False, 'full_parity_granted': False,
                         'complete_native_gate_acceptance_granted': False, 'rewrite_done_granted': False,
                         'entries': entries})
    print(json.dumps({'entries': len(entries), 'snapshot_unchanged': before == after,
                      'archives': env['archive_availability_counts'], 'models': src['trained_hdf5_count'],
                      'dipperstein_external_candidates': len(src['dipperstein_related_external_files']),
                      'gpu_exit_code': env['gpu_probe']['exit_code']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
