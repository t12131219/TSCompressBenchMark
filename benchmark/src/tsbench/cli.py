"""Build, inspect, run and describe one declared experiment."""
from pathlib import Path
import argparse
import json
import sys
from . import __version__


def _json(value):
    print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))


def inspect_experiment(config):
    from .data import load_dataset,project,object_id,raw_bytes,array_descriptor
    from .schemes import capability
    from .registry import Registry
    registry=Registry(config['_asset_root'])
    cases=[];datasets=[]
    for dataset in config['datasets']:
        obj=project(load_dataset(dataset,config['_base_dir']),config['task'])
        datasets.append({'id':dataset['id'],'raw_object_id':object_id(obj),'raw_bytes':raw_bytes(obj),
                         'components':{k:array_descriptor(a) for k,a in obj.components.items()},'lineage':dict(obj.lineage)})
        for method in config['methods']:
            resolved={**method,'params':registry.resolve_params(method['codec'],method.get('params',{}))}
            if 'components' in method:
                resolved['components']={k:{**v,'params':registry.resolve_params(v['codec'],v.get('params',{}))} for k,v in method['components'].items()}
            for profile in config['profiles']:
                cases.append({'dataset_id':dataset['id'],'method_id':method['id'],'profile_id':profile['id'],'resolved_method':resolved,
                              **capability(resolved,obj,config['task'],profile,asset_root=config['_asset_root'],build_root=config['_build_root'])})
    return {'schema':'tsbench.inspection/1','resolved_config':config,'datasets':datasets,'cases':cases,
            'requested_cases':len(cases),'executable_cases':sum(c['supported'] for c in cases),'measurement_executed':False}


def main(argv=None):
    parser=argparse.ArgumentParser(prog='tsbench',description=__doc__)
    parser.add_argument('--version',action='version',version=__version__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('build');p.add_argument('keys',nargs='*');p.add_argument('--all',action='store_true');p.add_argument('--force',action='store_true');p.add_argument('--asset-root',type=Path);p.add_argument('--build-root',type=Path)
    p=sub.add_parser('build-driver');p.add_argument('--asset-root',type=Path);p.add_argument('--build-root',type=Path)
    for name in ('inspect','run'):
        p=sub.add_parser(name);p.add_argument('config',type=Path)
        if name=='run':
            p.add_argument('--resume',action='store_true');p.add_argument('--retry',action='store_true');p.add_argument('--output',type=Path)
    p=sub.add_parser('report');p.add_argument('run',type=Path)
    p=sub.add_parser('profile');p.add_argument('manifest',type=Path);p.add_argument('--interval-ms',type=float,default=10)
    p=sub.add_parser('decode');p.add_argument('wire',type=Path);p.add_argument('output',type=Path);p.add_argument('--asset-root',type=Path);p.add_argument('--build-root',type=Path)
    p=sub.add_parser('codecs');p.add_argument('--asset-root',type=Path)
    args=parser.parse_args(argv)
    from .schemes import ASSET_ROOT
    if args.command=='build-driver':
        from .native import ensure_driver
        _json(ensure_driver(args.asset_root or ASSET_ROOT,args.build_root or (args.asset_root or ASSET_ROOT)/'build/tsbench'))
        return 0
    if args.command=='build':
        from .build import build_all
        if not args.all and not args.keys:parser.error('build needs keys or --all')
        records=build_all(args.asset_root or ASSET_ROOT,None if args.all else args.keys,force=args.force,build_root=args.build_root)
        _json(records)
        return 0 if all(r['status']=='ok' for r in records) else 1
    if args.command in {'inspect','run'}:
        from .config import load
        config=load(args.config)
        if args.command=='inspect':_json(inspect_experiment(config));return 0
        from .runner import run
        path=run(config,output=args.output.resolve() if args.output else None,resume=args.resume,retry=args.retry)
        from .report import generate
        result=generate(path)
        _json({'run':str(path),'report':str(Path(path)/'report/README.md'),'requested_cases':result['requested_cases'],
               'case_statuses':result['requested_case_status_counts'],'planned_trials':result['planned_trials'],
               'statuses':result['status_counts']})
        return 0
    if args.command=='report':
        from .report import generate
        _json(generate(args.run));return 0
    if args.command=='profile':
        from .profile import run_profile
        _json({'profile_run':str(run_profile(args.manifest,args.interval_ms))});return 0
    if args.command=='decode':
        from .worker import _decode_wire
        _decode_wire(args.wire,args.output,args.asset_root or ASSET_ROOT,args.build_root)
        _json({'output':str(args.output)});return 0
    if args.command=='codecs':
        from .registry import Registry
        _json([{'key':s.key,'status':'excluded' if s.excluded else 'enabled','reason':s.exclusion_reason,
                'dtypes':s.dtypes,'ranks':s.ranks,'loss_mode':s.loss_mode,'threading':s.threading,'isa':s.isa}
               for s in Registry(args.asset_root or ASSET_ROOT).list(include_excluded=True)]);return 0
    return 2


def entrypoint():
    try:return main()
    except (ValueError,OSError,RuntimeError) as exc:
        print(f'tsbench: {type(exc).__name__}: {exc}',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(entrypoint())
