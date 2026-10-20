"""Finish predeclared supplemental runs and render after the active CPU sweep.

This companion waits for the existing sequential sweep, so it never starts a
second measurement alongside it. It then resumes the same frozen design and
generates the final (strictly complete, audited) report automatically.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design',type=Path)
    parser.add_argument('--await-configurations',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    design_path=args.design.resolve()
    design=json.loads(design_path.read_text())
    root=Path(design['run_root'])
    state=root/'completion_pipeline.json'
    def record(status,**extra):
        state.write_text(json.dumps({'status':status,'updated_at':datetime.now().astimezone().isoformat(),**extra},indent=2))
    record('waiting_for_existing_sequential_sweep',await_configurations=args.await_configurations)
    while True:
        progress=root/'orchestration.json'
        if progress.exists():
            try:
                current=json.loads(progress.read_text())
            except json.JSONDecodeError:
                time.sleep(5)
                continue
            if current['completed_configurations']>=args.await_configurations:
                if any(r['returncode'] for r in current['runs']):
                    record('experiment_error_requires_review',orchestration=str(progress))
                    return 1
                break
        time.sleep(30)
    record('completing_frozen_design')
    commands=[[sys.executable,str(ROOT/'benchmark/tools/forecasting_benchmark.py'),'run',str(design_path.parent)]]
    for command in commands:
        result=subprocess.run(command)
        if result.returncode:
            record('error',command=command,returncode=result.returncode)
            return result.returncode
    design=json.loads(design_path.read_text())
    if design.get('gpu_configurations'):
        record('building_gpu_asset_after_cpu')
        command=[sys.executable,str(ROOT/'benchmark/tools/build_cuszp.py'),'--architecture','75']
        with (root/'gpu-build.log').open('ab') as stream:
            result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            record('gpu_build_error',returncode=result.returncode,log=str(root/'gpu-build.log'))
            return result.returncode
        gpu_runs=[]
        for entry in design['gpu_configurations']:
            directory=Path(entry['run'])
            record('running_gpu',configuration=entry['path'],run=str(directory))
            if not (directory/'summary.json').exists():
                command=[sys.executable,'-m','tsbench.gpu','run',entry['path']]
                with (root/(Path(entry['path']).stem+'.log')).open('ab') as stream:
                    result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
                if result.returncode:
                    record('gpu_run_error',command=command,returncode=result.returncode)
                    return result.returncode
            summary=json.loads((directory/'summary.json').read_text())
            gpu_runs.append({'configuration':entry['path'],'run':str(directory),
                             'requests':len(summary['cases']),
                             'complete_cases':sum(c['complete_success'] for c in summary['cases']),
                             'terminal_status_counts':summary['terminal_status_counts']})
            (root/'gpu_orchestration.json').write_text(json.dumps({'runs':gpu_runs},indent=2))
        availability=design_path.parent/'gpu_availability.json'
        current=json.loads(availability.read_text())
        current.update(status='measured',measurement_executed=True,gpu_execution_pending=False,runs=gpu_runs)
        availability.write_text(json.dumps(current,ensure_ascii=False,indent=2))
    record('auditing_and_rendering_report')
    command=[sys.executable,str(ROOT/'benchmark/tools/report_forecasting_results.py'),str(design_path),'--output',str(args.output.resolve())]
    result=subprocess.run(command)
    if result.returncode:
        record('report_error',command=command,returncode=result.returncode)
        return result.returncode
    record('complete',report=str(args.output.resolve()/('visual_report_'+design_path.parent.name.replace('forecasting-','')+'.md')))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
