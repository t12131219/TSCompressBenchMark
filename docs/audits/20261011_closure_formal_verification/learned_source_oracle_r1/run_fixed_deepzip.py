"""Execute only the pre-frozen three-context DeepZip source diagnostic."""
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path):
    return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def main():
    plan_path = Path(sys.argv[1]).resolve()
    plan = json.loads(plan_path.read_text())
    output = Path(plan['output'])
    output.mkdir(exist_ok=False)
    commands = []
    environment = dict(os.environ)
    for name in ['PYTHONPATH', 'LD_PRELOAD', 'LD_AUDIT']:
        environment.pop(name, None)
    environment.update(plan['environment'])
    for key in ['KERAS_HOME', 'TMPDIR']:
        Path(environment[key]).mkdir(exist_ok=False)
    report = dict(schema_version='tscb.fresh-source-fixed-weight-differential.v1',
                  plan=ref(plan_path), commands=commands, production_changed=False,
                  training_executed=False, formal_performance_executed=False,
                  all_required_gates_qualified=False)
    try:
        for key in plan['immutable_refs']:
            item = plan[key]
            if sha(Path(item['path'])) != item['sha256']:
                raise RuntimeError('frozen input changed: ' + key)
        for label in ['compile', 'source', 'native']:
            command = plan['commands'][label]
            started = time.monotonic()
            process = subprocess.run(command, cwd=plan['root'], env=environment,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            stdout, stderr = output / (label + '.stdout.log'), output / (label + '.stderr.log')
            stdout.write_bytes(process.stdout)
            stderr.write_bytes(process.stderr)
            record = dict(label=label, command=command, exit_code=process.returncode,
                          elapsed_seconds=time.monotonic()-started, stdout=ref(stdout), stderr=ref(stderr))
            commands.append(record)
            save(output / (label + '.receipt.json'), record)
            print(label + ': exit ' + str(process.returncode), flush=True)
            if process.returncode:
                raise RuntimeError(label + ' command failed; original logs retained')
        source = json.loads((output / 'source/report.json').read_text())
        if source['status'] != 'FIXED_WEIGHT_SOURCE_DIAGNOSTIC_PASS':
            raise RuntimeError('source diagnostic has gaps')
        source_prob = struct.unpack('<12f', (output/'source/probabilities.f32').read_bytes())
        native_prob = struct.unpack('<12f', (output/'native.probabilities.f32').read_bytes())
        source_cdf = struct.unpack('<15Q', (output/'source/cumulative.u64').read_bytes())
        native_cdf = struct.unpack('<15Q', (output/'native.cumulative.u64').read_bytes())
        table_replay = struct.unpack('<15Q', (output/'native.source-probability-cumulative.u64').read_bytes())
        rows = []
        for row in range(3):
            elements = []
            for column in range(4):
                index = row*4+column
                absolute = abs(native_prob[index]-source_prob[index])
                finite = math.isfinite(source_prob[index]) and math.isfinite(native_prob[index])
                elements.append(dict(column=column, source=source_prob[index], native=native_prob[index],
                                     absolute_error=absolute, finite=finite,
                                     within_frozen_absolute_tolerance=finite and absolute <= plan['probability_absolute_tolerance']))
            rows.append(dict(row=row, context=plan['context_descriptions'][row], probabilities=elements,
                             source_cdf=list(source_cdf[row*5:(row+1)*5]),
                             native_cdf=list(native_cdf[row*5:(row+1)*5]),
                             native_cdf_from_identical_source_probabilities=list(table_replay[row*5:(row+1)*5]),
                             cdf_integer_difference=[native_cdf[row*5+column]-source_cdf[row*5+column] for column in range(5)]))
        probability_pass = all(v['within_frozen_absolute_tolerance'] for row in rows for v in row['probabilities'])
        conversion_exact = source_cdf == table_replay
        prediction_cdf_exact = source_cdf == native_cdf
        artifact_path = Path(plan['artifact']['path']).resolve()
        maps = (output/'native.maps').read_text()
        mapped = [line for line in maps.splitlines() if str(artifact_path) in line]
        if not mapped or sha(artifact_path) != plan['artifact']['sha256']:
            raise RuntimeError('exact registered artifact runtime binding not confirmed')
        if sha(Path(plan['model_original']['path'])) != plan['model_original']['sha256']:
            raise RuntimeError('registered model changed during diagnostic')
        report.update(status='FIXED_WEIGHT_PROBABILITY_AND_IDENTICAL_INPUT_CDF_DIAGNOSTIC_PASS' if probability_pass and conversion_exact else 'FAIL',
                      rows=rows, probability_absolute_tolerance=plan['probability_absolute_tolerance'],
                      probability_max_absolute_error=max(v['absolute_error'] for row in rows for v in row['probabilities']),
                      all_12_probabilities_within_tolerance=probability_pass,
                      source_numpy_to_current_cdf_identical_inputs_exact=conversion_exact,
                      independently_predicted_cdf_exact=prediction_cdf_exact,
                      source_report=ref(output/'source/report.json'), source_actual_cudnn_gpu_nodes=source['actual_cudnn_gpu_nodes'],
                      registered_artifact=ref(artifact_path), registered_artifact_runtime_mapping_lines=mapped,
                      harness=ref(output/'current-artifact-predict'),
                      claim_boundary='Only biGRU alphabet4 frozen current weights and 3 contexts; no training, initializer equivalence, other constructors, GPU native profile, HDF5 import, lanes/tails or complete source pipeline. Probability tolerance cannot imply identical independent CDF or source bitstream. All original REQUIRED_PARITY rows remain required.')
    except Exception as error:
        report.update(status='EXECUTION_OR_DIFFERENTIAL_FAILED', error_type=type(error).__name__, error=str(error))
    report['driver'] = ref(Path(__file__).resolve())
    report['outputs'] = [ref(path) for path in sorted(output.rglob('*')) if path.is_file()]
    save(output / 'report.json', report)
    print(json.dumps({key:report[key] for key in ['status','all_12_probabilities_within_tolerance','source_numpy_to_current_cdf_identical_inputs_exact','independently_predicted_cdf_exact','probability_max_absolute_error'] if key in report}), flush=True)
    return 0 if report['status']=='FIXED_WEIGHT_PROBABILITY_AND_IDENTICAL_INPUT_CDF_DIAGNOSTIC_PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
