"""Exercise the frozen short Zstd dictionary tier, without changing tier on failure."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import tempfile

from tsbench.assets import canonical_bytes, content_id, digest, load_json, require, verify_asset
from tsbench.corpus_ingress import load_full_manifest, read_batches
from tsbench.planner.native_corpus import verify_native_corpus_plan
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, program_files

ROOT = Path(__file__).resolve().parents[2]


def _write(path, obj):
    with path.open('xb') as f:
        f.write(canonical_bytes(obj) + b'\n')


def _ref(root, path):
    return {'path': path.relative_to(root).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size}


def _slices(entry, layout):
    """All slices are from the verified source; only train slices reach the trainer."""
    stride = 8*entry['value_count']
    train, _, test = entry['partitions']
    size = layout['consumed_byte_range'][1]
    frame_limit = layout['evaluation']['frame_input_limit_bytes']
    require(layout['consumed_byte_range'][0] == 0 and size <= (train['end']-train['start'])*stride and
            layout['partition_object_id'] == train['canonical']['object_id'] and
            layout['evaluation']['partition_object_id'] == test['canonical']['object_id'] and
            layout['evaluation']['absolute_rows'] == [test['start'], test['end']] and
            (test['end']-test['start'])*stride <= frame_limit, 'invalid short probe train/test ranges')
    spans = ((train['start']*stride, train['start']*stride+size), (test['start']*stride, test['end']*stride))
    slices = [bytearray(), bytearray()]
    for batch in read_batches(ROOT, entry):
        first, past = batch.start*stride, (batch.start+batch.rows)*stride
        for (lo, hi), blob in zip(spans, slices, strict=True):
            if first < hi and lo < past:
                blob.extend(batch.values[max(lo, first)-first:min(hi, past)-first])
    require(all(len(x)==hi-lo for (lo,hi),x in zip(spans,slices,strict=True)), 'incomplete train/test slices')
    g = layout['sample_geometry']
    each = g['bytes_each']
    require(g['first_byte']==0 and g['stride_bytes']==each and g['count']*each==size, 'short sample geometry differs')
    return [bytes(slices[0][i:i+each]) for i in range(0, size, each)], bytes(slices[1])


def run(args):
    definition = load_json(args.definition)
    verify_native_corpus_plan(ROOT, definition)
    corpus = load_full_manifest(ROOT, definition['bindings']['manifest'])
    entries = {e['id']: e for e in corpus['datasets']}
    cases = [(d, d['input']['training']) for d in definition['decisions'] if d['route']=='zstd-dictionary' and
             d['state']=='input_domain_matches' and d['input']['training']['extent_tier']=='short']
    prior = load_json(args.previous_run/'plan.json')
    runtime = prior['decoder']
    key, = [k for k,v in runtime['tools'].items() if Path(v).name=='tsbench_lzbench_feature_control']
    limits = {'address_space_bytes': 128 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}
    plan = {'purpose':'development_zstd_short_train_not_acceptance', 'corpus_plan_content_id':definition['plan_content_id'],
            'build_id':prior['build']['build_id'], 'runtime':runtime, 'tool':key, 'limits':limits,
            'case_ids':[d['decision_id'] for d,_ in cases], 'probe_sha256':digest(Path(__file__))}
    plan['plan_content_id'] = content_id(plan)
    out = args.out.resolve()
    out.mkdir(parents=True)
    _write(out/'plan.json', plan)
    for relative in program_files(runtime, [runtime['tools'][key]]):
        src = verify_asset(args.previous_run/'recovery', {'path':relative, 'sha256':runtime['files'][relative]['sha256']})
        target = out/'recovery'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    rows = []
    with (out/'ledger.jsonl').open('xb') as ledger:
        for dec, layout in cases:
            dataset = dec['dataset_id']
            training, held = _slices(entries[dataset], layout)
            artifacts, logs = out/'products'/dataset, out/'logs'/dataset
            artifacts.mkdir(parents=True); logs.mkdir(parents=True)
            with tempfile.TemporaryDirectory(prefix='tsbench-zstd-short-') as td:
                work = Path(td)
                names = [f'sample-{i:03d}' for i in range(len(training))]
                train_inputs = {name:work/name for name in names}
                for p, b in zip(train_inputs.values(), training, strict=True):
                    p.write_bytes(b)
                row = {'dataset':dataset, 'decision_id':dec['decision_id'], 'training':layout, 'operations':{}}

                def invoke(label, inputs, argv):
                    step = work/label
                    step.mkdir()
                    produced, op = invoke_isolated_tool(out/'recovery', runtime, key, limits, step, logs,
                                                       label, inputs, argv, lambda: False, observe=True)
                    row['operations'][label] = op
                    return produced, op

                cap = layout['dictionary_capacity_bytes']
                native, op = invoke('train', train_inputs, ['train', str(cap), 'dict', *['/inputs/'+n for n in names]])
                if op['status']=='completed':
                    dictionary = native/'dict'
                    raw_dict = dictionary.read_bytes()
                    require(8 <= len(raw_dict) <= cap and raw_dict[:4]==bytes.fromhex('37a430ec') and
                            int.from_bytes(raw_dict[4:8], 'little')!=0, 'invalid native trained dictionary')
                    shutil.copy2(dictionary, artifacts/'dict')
                    test_file = work/'held'
                    test_file.write_bytes(held)

                    def frame(label, source, decode, use_dict=True):
                        inputs = {'source': source, **({'dict':artifacts/'dict'} if use_dict else {})}
                        return invoke(label, inputs, ['decode' if decode else 'roundtrip','zstd','frame','3','307','521',
                                      '65536','reuse','1','/inputs/dict' if use_dict else '-', '/inputs/source',
                                      'wire','raw',str(len(held))])

                    encoded, enc = frame('encode-test', test_file, False)
                    require(enc['status']=='completed' and (encoded/'raw').read_bytes()==held, 'held-out encode/restore differs')
                    shutil.copy2(encoded/'wire', artifacts/'wire')
                    restored, dec_op = frame('detached-restore', artifacts/'wire', True)
                    require(dec_op['status']=='completed' and set(dec_op['input_mounts'])=={'dict','source'} and
                            (restored/'raw').read_bytes()==held and (restored/'wire').read_bytes()==(artifacts/'wire').read_bytes(),
                            'detached held-out restore differs')
                    neg, refused = frame('reject-missing-dictionary', artifacts/'wire', True, False)
                    require(refused['status']=='failed' and refused['returncode']==2 and not list(neg.iterdir()) and
                            'Dictionary mismatch' in (logs/'reject-missing-dictionary.stderr').read_text(),
                            'trained frame failed to reject missing dictionary')
                    row.update(status='verified', assets=[_ref(out, artifacts/k) for k in ('dict','wire')],
                               restored_bytes=len(held), restored_sha256=digest(restored/'raw'))
                elif op['status']=='failed' and op['returncode']==2 and not list(native.iterdir()):
                    row.update(status='native_training_rejected', reason=(logs/'train.stderr').read_text().strip(),
                               test_attempted=False, training_fallback=False)
                else:
                    row.update(status=op['status'], reason=op['reason'], test_attempted=False, training_fallback=False)
            rows.append(row)
            ledger.write(canonical_bytes(row)+b'\n'); ledger.flush()
    _write(out/'report.json', {'plan_content_id':plan['plan_content_id'], 'denominator':len(cases),
        'statuses':dict(Counter(r['status'] for r in rows)), 'rows':rows, 'stage_accepted':False, 'timing_admitted':False})
    require(all(r['status'] in {'verified','native_training_rejected'} for r in rows), 'short dictionary probe infrastructure failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition', type=Path, required=True)
    parser.add_argument('--previous-run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args())
