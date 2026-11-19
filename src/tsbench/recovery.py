"""Frozen decoder closure for the Linux x86-64/glibc lossless candidate.

Only inspect and execute trusted native build outputs. This is an internal
recovery bundle, not a port of arbitrary plugins or a redistribution claim.
"""
from pathlib import Path, PurePosixPath
import os
import re
import shutil
import subprocess
import tempfile

from .assets import ContractError, content_id, digest, local_file, require, verify_asset

DIRECTORY = 'recovery'
MANIFEST = 'recovery.json'
SCHEMA = 'bmk.dev-recovery-plan/1'
TOOLS_SCHEMA = 'bmk.dev-recovery-plan/2'
STANDALONE_SCHEMA = 'bmk.dev-tool-recovery-plan/1'
PLATFORM = 'linux-x86_64-glibc-distribution-multiarch'
LOADER = 'ld-linux-x86-64.so.2'
SYSTEM = frozenset({LOADER, 'libc.so.6', 'libm.so.6', 'libgcc_s.so.1', 'libstdc++.so.6',
                    'libdl.so.2', 'libpthread.so.0', 'librt.so.1', 'libgomp.so.1'})
SYSTEM_ROOT = Path('/usr/lib/x86_64-linux-gnu')
_SAFE_NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.+-]{0,127}\Z')


def _expected(build, methods, tools, libraries=None):
    if libraries is not None:
        require(not build and not methods and tools and libraries, 'invalid standalone recovery roots')
        worker_path, native = None, {}
    else:
        worker = build['worker']
        worker_path = f"bin/{PurePosixPath(worker['path']).name}"
        native = {worker_path:worker}
    plugins = {}
    for name in sorted(methods):
        item = build['plugins'][name]
        plugins[name] = f"lib/{PurePosixPath(item['library']['path']).name}"
    refs = (libraries if libraries is not None else
            [r for name in sorted(methods) for r in [build['plugins'][name]['library'],*build['plugins'][name]['dependencies']]])
    for ref in refs:
        basename = PurePosixPath(ref['path']).name
        key = f'lib/{basename}'
        require(basename not in SYSTEM and (key not in native or native[key]['sha256']==ref['sha256']),
                f'conflicting recovery library basename: {basename}')
        native[key] = ref
    executables = {}
    for name, ref in sorted(tools.items()):
        require(_SAFE_NAME.fullmatch(name) and set(ref) == {'path', 'sha256'}, 'invalid recovery control identity')
        path = 'bin/' + PurePosixPath(ref['path']).name
        require(path not in native, 'conflicting recovery executable basename')
        executables[name] = path
        native[path] = ref
    return worker_path, plugins, native, executables


def _readelf(path, flag):
    try:
        result = subprocess.run(['/usr/bin/readelf',flag,str(path)],capture_output=True,text=True,
                                env={'LC_ALL':'C'},timeout=10,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ContractError('local readelf is required to freeze decoder dependencies') from exc
    require(result.returncode==0 and not result.stderr, f'cannot inspect trusted recovery ELF: {path.name}')
    return result.stdout


def _dynamic(path, name, *, project):
    doc = _readelf(path,'-Wd')
    require('Dynamic section at offset' in doc, f'not a supported dynamic ELF: {name}')
    values = lambda tag: re.findall(rf'\({tag}\)[^\n]*?\[([^\]]*)\]',doc)
    soname = values('SONAME')
    require(not soname or soname==[name],f'SONAME does not match recovery path: {name}')
    require(not re.search(r'\((AUDIT|DEPAUDIT|FILTER|AUXILIARY)\)',doc), 'undeclared dynamic-loader extension')
    if project:
        require(all(s in {'$ORIGIN','${ORIGIN}'} for s in values('RPATH')+values('RUNPATH')),
                f'nonlocal runpath cannot enter recovery closure: {name}')
    needs = values('NEEDED')
    require(all(_SAFE_NAME.fullmatch(d) for d in needs) and len(needs)==len(set(needs)),
            f'invalid ELF dependency name: {name}')
    return needs


def _source(root, item):
    if item['origin']=='build':
        return verify_asset(root,{'path':item['source'],'sha256':item['sha256']})
    require(item['origin']=='system' and item['source'] in SYSTEM,'unsupported system recovery library')
    path = local_file(SYSTEM_ROOT,item['source'])
    require(digest(path)==item['sha256'],f'system recovery library changed: {item["source"]}')
    return path


def plan_recovery(root, build, methods, *, tools=None, libraries=None):
    worker, plugins, native, executables = _expected(build, methods, tools or {}, libraries)
    for key in ([worker] if worker else []) + list(executables.values()):
        executable = verify_asset(root, native[key])
        interp = re.findall(r'Requesting program interpreter: ([^\]]+)', _readelf(executable, '-Wl'))
        require(interp == ['/lib64/' + LOADER], 'unsupported recovery ELF interpreter')
    files = {}
    for key,ref in native.items():
        file = verify_asset(root,ref)
        files[key] = {'origin':'build','source':ref['path'],'sha256':ref['sha256'],'bytes':file.stat().st_size,
                      'needed':_dynamic(file,PurePosixPath(key).name,project=True)}
    pending = [LOADER,*(n for row in files.values() for n in row['needed'])]
    while pending:
        name = pending.pop()
        key = f'lib/{name}'
        if key not in files:
            require(name in SYSTEM,f'undeclared recovery dependency: {name}')
            file = local_file(SYSTEM_ROOT,name)
            row = {'origin':'system','source':name,'sha256':digest(file),'bytes':file.stat().st_size,
                   'needed':_dynamic(file,name,project=False)}
            files[key] = row
            pending.extend(row['needed'])
    body = {'schema':SCHEMA,'platform':PLATFORM,'build_id':_build_id(build,tools,libraries),'worker':worker,'plugins':plugins,
            'loader':f'lib/{LOADER}','files':files}
    if executables:
        body.update(schema=TOOLS_SCHEMA, tools=executables)
    if libraries is not None:
        body['schema'] = STANDALONE_SCHEMA
    result = {**body,'recovery_id':content_id(body)}
    check_recovery(result,build,methods,tools=tools,libraries=libraries)
    return result


def _build_id(build, tools, libraries):
    return build['build_id'] if libraries is None else content_id({'tools':tools,'libraries':libraries})


def check_recovery(spec, build, methods, *, tools=None, libraries=None):
    fields = {'schema','platform','build_id','worker','plugins','loader','files','recovery_id'}
    expected_schema = STANDALONE_SCHEMA if libraries is not None else TOOLS_SCHEMA if tools else SCHEMA
    if tools:
        fields.add('tools')
    require(isinstance(spec,dict) and set(spec)==fields and spec['schema']==expected_schema and spec['platform']==PLATFORM and
            spec['recovery_id']==content_id({k:v for k,v in spec.items() if k!='recovery_id'}), 'invalid recovery closure identity')
    worker, plugins, native, executable = _expected(build, methods, tools or {}, libraries)
    require(spec['build_id']==_build_id(build,tools,libraries) and spec['worker']==worker and spec['plugins']==plugins and spec.get('tools', {})==executable and
            spec['loader']=='lib/'+LOADER and isinstance(spec['files'],dict) and set(native)<=spec['files'].keys() and spec['loader'] in spec['files'],
            'recovery binding differs from frozen build or methods')
    for key, row in spec['files'].items():
        name = PurePosixPath(key).name
        require(_SAFE_NAME.fullmatch(name) and key in {f'lib/{name}', worker, *executable.values()} and
                isinstance(row,dict) and set(row)=={'origin','source','sha256','bytes','needed'} and
                isinstance(row['sha256'],str) and re.fullmatch('[0-9a-f]{64}',row['sha256']) and
                type(row['bytes']) is int and row['bytes']>0 and isinstance(row['needed'],list) and
                all(isinstance(n,str) and _SAFE_NAME.fullmatch(n) and 'lib/'+n in spec['files'] for n in row['needed']) and
                len(row['needed'])==len(set(row['needed'])), 'invalid recovery dependency record')
        if key in native:
            require(row['origin']=='build' and row['source']==native[key]['path'] and row['sha256']==native[key]['sha256'],
                    'recovery file does not match build lock')
        else:
            require(row['origin']=='system' and name==row['source'] and name in SYSTEM, 'undeclared system recovery file')
    reached = set(native) if libraries is None else set()
    pending = ([spec['loader'],*(f'lib/{n}' for item in native for n in spec['files'][item]['needed'])]
               if libraries is None else [spec['loader'],*executable.values()])
    while pending:
        key = pending.pop()
        if key not in reached:
            reached.add(key)
            pending.extend(f'lib/{n}' for n in spec['files'][key]['needed'])
    require(reached==spec['files'].keys(),'unreferenced file in recovery closure')


def stage_recovery(root, run, spec, *, directory=DIRECTORY):
    """Verify all source identities before copying one shared closure per run."""
    require(_SAFE_NAME.fullmatch(directory), 'invalid stage recovery namespace')
    sources = {name:_source(root,row) for name,row in spec['files'].items()}
    # Publish the complete directory at once; a failed copy cannot become a partial package.
    with tempfile.TemporaryDirectory(prefix='.stage-recovery-',dir=run) as tmp:
        staged = Path(tmp)/DIRECTORY
        (staged/'bin').mkdir(parents=True)
        (staged/'lib').mkdir()
        for name,src in sources.items():
            target = staged/name
            with src.open('rb') as inp, target.open('xb') as out:
                shutil.copyfileobj(inp,out)
                out.flush()
                os.fchmod(out.fileno(), 0o500 if name in (spec['worker'], spec['loader'], *spec.get('tools', {}).values()) else 0o400)
                os.fsync(out.fileno())
            item = spec['files'][name]
            require(target.stat().st_size==item['bytes'] and digest(target)==item['sha256'],
                    f'staged recovery file differs: {name}')
        staged.rename(run/directory)
    return [run/directory/name for name in sorted(sources)]


def verify_recovery_binding(plan, metadata, sealed, verified, *, pre_staged=False):
    spec = plan['contract_bindings']['recovery']
    check_recovery(spec,plan['build'],plan['methods'])
    require(isinstance(metadata,dict) and set(metadata)=={'recovery_id','status','reason','sample_slots'} and
            metadata['recovery_id']==spec['recovery_id'] and metadata['sample_slots']==sorted(verified) and
            isinstance(metadata['reason'],str),
            'recovery metadata differs from run slots')
    packaged = {path:row for path,row in sealed.items() if path.startswith(DIRECTORY+'/')}
    if metadata['status']=='ready':
        expected = {path:{'path':path,'sha256':row['sha256'],'bytes':row['bytes']}
                    for rel,row in spec['files'].items() for path in [f'{DIRECTORY}/{rel}']}
        require((pre_staged or bool(verified)) and metadata['reason']=='' and packaged==expected,
                'recovery package is incomplete')
    elif metadata['status']=='unavailable':
        require(not pre_staged and bool(verified) and bool(metadata['reason']) and not packaged,
                'invalid unavailable recovery evidence')
    elif metadata['status']=='setup_failed':
        require(pre_staged and not verified and bool(metadata['reason']) and not packaged,
                'invalid pre-launch recovery setup failure evidence')
    else:
        require(metadata['status']=='no_verified_samples' and not verified and metadata['reason']=='' and not packaged,
                'invalid empty recovery evidence')
    return {**metadata,'files':len(packaged),'bytes':sum(row['bytes'] for row in packaged.values())}
