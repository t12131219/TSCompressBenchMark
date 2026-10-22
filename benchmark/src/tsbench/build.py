"""Build frozen native assets independently of the former benchmark framework."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
from pathlib import Path

from . import _native_recipes as recipes
from .errors import Unavailable
from .registry import Registry
from .families import CAMEO_FAMILY

_RW = {'deepzip': 7, 'dzip': 8}
_ABBA_FAMILY = {'abba', 'fabba', 'qabba'}
_FOLDERS = {
    'alp': 'alp', 'alp-rd': 'alp', 'serf-qt': 'serf', 'serf-xor': 'serf',
    'huff0': 'entropy_fse', 'fse': 'entropy_fse',
    'neats-lossless-i64': 'neats', 'leats-lossless-i64': 'neats',
    'zfp-accuracy-1d': 'zfp', 'simdcomp-u32': 'simdcomp',
    'lzss-dipperstein-c': 'lzss_dipperstein',
}
for _key in ('elf', 'elf-plus', 'elf-star', 'self-star'):
    _FOLDERS[_key] = 'rewrite_lossless'
for _key in recipes.SPRINTZ_FAMILY:
    _FOLDERS[_key] = 'sprintz_family'
for _key in recipes.CHIMP_FAMILY:
    _FOLDERS[_key] = 'chimp_family'
for _key in CAMEO_FAMILY:
    _FOLDERS[_key] = 'cameo_family'
for _key in _ABBA_FAMILY:
    _FOLDERS[_key] = 'abba_family'
for _key in _RW:
    _FOLDERS[_key] = 'completed_rewrites'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _build_base(root: Path, build_root=None) -> Path:
    path = Path(build_root) if build_root is not None else Path('build/tsbench')
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def artifact_path(root: str | Path, key: str, build_root=None) -> Path:
    root = Path(root).resolve()
    key = Registry(root).get(key).key
    base = _build_base(root,build_root)
    index = base / (key + '.index.json')
    if index.is_file():
        record = json.loads(index.read_text())
        return Path(record['artifact'])
    return base / 'unbuilt' / key / ('libtscb_' + key.replace('-', '_') + '.so')


def _source_files(root: Path, key: str) -> list[dict]:
    folder = root / 'adapters' / _FOLDERS.get(key, key.replace('-', '_'))
    folders = [folder, root / 'native/include']
    if key == 'lzsse8-raw':
        folders.append(root / 'adapters/lzsse2_raw/native')
    entries = []
    for base in folders:
        if not base.is_dir():
            raise Unavailable(f'missing native asset directory: {base}', stage='build')
        for path in sorted(base.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                entries.append({'path': str(path.relative_to(root)), 'sha256': sha(path)})
    for path, module in [(Path(__file__), 'build.py'), (Path(recipes.__file__), '_native_recipes.py'), (Path(__file__).with_name('families.py'), 'families.py')]:
        path = path.resolve()
        try:
            entry = {'path': str(path.relative_to(root)), 'sha256': sha(path)}
        except ValueError:
            # Installed build code is part of the recipe identity, not an asset
            # file below the caller's separately declared source checkout.
            entry = {'path': 'package:tsbench/' + module, 'source_path': str(path), 'sha256': sha(path)}
        entries.append(entry)
    card = root / 'registry/codecs' / (key + '.json')
    entries.append({'path': str(card.relative_to(root)), 'sha256': sha(card)})
    return entries


def _run(command: list[str]) -> str:
    return recipes._run(command)


def _compile_native(command: list[str], output: Path) -> None:
    """Preserve every real translation unit's system-header Make dependency file."""
    sources = [value for value in command[1:] if Path(value).suffix in {'.c','.cc','.cpp'}]
    flags = []
    skip = False
    for value in command[1:]:
        if skip:
            skip = False
            continue
        if value == '-o':
            skip = True
        elif value in sources or value == '-shared' or value.startswith(('-Wl,','-l')) or Path(value).suffix in {'.a','.o','.so'}:
            continue
        else:
            flags.append(value)
    objects = output.parent / 'objects'
    objects.mkdir()
    substitutions = {}
    for index,source in enumerate(sources):
        obj = objects / f'{index:03d}_{Path(source).stem}.o'
        cxx = Path(source).suffix in {'.cc','.cpp'}
        compiler = command[0]
        unit_flags = flags
        # Compile genuine C sources as C and the direct C++ shim as C++; retain
        # separate dependency files and link mixed units with the C++ runtime.
        if cxx and any(flag.startswith('-std=c') and not flag.startswith('-std=c++') for flag in flags):
            compiler = os.environ.get('CXX','c++')
            unit_flags = [flag for flag in flags if not flag.startswith('-std=')] + ['-std=c++17']
        _run([compiler,*unit_flags,'-c','-MD','-MF',str(obj.with_suffix('.o.d')),
              '-MT',str(obj),source,'-o',str(obj)])
        substitutions[source] = str(obj)
    link = [substitutions.get(value,value) for value in command]
    if any(Path(source).suffix in {'.cc','.cpp'} for source in sources):
        link[0] = os.environ.get('CXX','c++') if any(Path(source).suffix == '.c' for source in sources) else command[0]
    _run(link)


def _compiled_dependencies(root: Path, folder: Path) -> list[dict]:
    shared = folder / 'compiled-family.json'
    if shared.is_file():
        return json.loads(shared.read_text())
    closure = set()
    files = [*folder.rglob('*.o.d'),*folder.glob('*.d')]
    if not files:
        raise RuntimeError('no actual compiler dependency files were produced')
    for path in files:
        data = path.read_text().replace('\\\n',' ')
        if ':' not in data:
            raise RuntimeError(f'invalid compiler dependency file: {path}')
        for value in shlex.split(data.split(':',1)[1],comments=False):
            entry = Path(value)
            if not entry.is_absolute():
                entry = root / entry
            closure.add(entry.resolve(strict=True))
    for path in folder.rglob('*.Plo'):
        # Automake emits phony header rules after the first dependency rule.
        first = path.read_text().replace('\\\n', ' ').split('\n', 1)[0]
        if ':' not in first:
            continue
        for value in shlex.split(first.split(':', 1)[1], comments=False):
            entry = Path(value)
            if not entry.is_absolute():
                entry = path.parent.parent / entry
            closure.add(entry.resolve(strict=True))
    return [{'path':str(path),'sha256':sha(path)} for path in sorted(closure)]


def _toolchain_dependencies(compilers: dict) -> list[dict]:
    programs = {Path(entry['path']) for entry in compilers.values()}
    for compiler in compilers:
        for name in ('cc1','cc1plus','as','collect2','ld','ar','ranlib'):
            done = subprocess.run([compiler,'-print-prog-name='+name],capture_output=True,text=True,check=True)
            path = shutil.which(done.stdout.strip())
            if path:
                programs.add(Path(path).resolve())
    return [{'path':str(path),'sha256':sha(path)} for path in sorted(programs)]


def _rw_build(root: Path, key: str, output: Path) -> None:
    adapter = root / 'adapters/completed_rewrites'
    lock = json.loads((adapter / 'FROZEN_SOURCES.json').read_text())
    for record in lock['packages'][key]['files']:
        if sha(root / record['path']) != record['sha256']:
            raise Unavailable(f'frozen source changed: {record["path"]}', stage='build')
    source = adapter / 'vendor' / key
    recipe = output.parent / 'recipe'
    recipe.mkdir()
    recipe.joinpath('CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.18)
project(tsbench_rw_binding LANGUAGES C CXX)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 17)
add_subdirectory("{source}" standalone EXCLUDE_FROM_ALL)
add_library(tsbench_binding SHARED "{adapter / 'native/binding.cpp'}")
target_link_libraries(tsbench_binding PRIVATE {key})
target_include_directories(tsbench_binding PRIVATE "{root / 'native/include'}")
target_compile_definitions(tsbench_binding PRIVATE RW_KIND={_RW[key]} RW_KEY="{key}")
set_target_properties(tsbench_binding PROPERTIES OUTPUT_NAME tscb_{key.replace('-', '_')}
 LIBRARY_OUTPUT_DIRECTORY "{output.parent}")
''')
    _run(['cmake', '-S', str(recipe), '-B', str(output.parent / 'cmake'),
          '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_FLAGS=-fno-fast-math -ffp-contract=off',
          '-DDEEPZIP_WITH_HDF5=OFF', '-DDEEPZIP_WITH_CUDA=OFF',
          '-DDZIP_WITH_HDF5=OFF', '-DDZIP_WITH_CUDA=OFF'])
    _run(['cmake', '--build', str(output.parent / 'cmake'), '--target', 'tsbench_binding', '--parallel', '2'])


def _abba_build(root: Path, key: str, output: Path) -> None:
    adapter = root / 'adapters/abba_family'
    lock = json.loads((adapter / 'FROZEN_SOURCES.json').read_text())
    for entry in lock['files']:
        if sha(root / entry['path']) != entry['sha256']:
            raise Unavailable(f'frozen ABBA family source changed: {entry["path"]}', stage='build')
    # Autotools can regenerate distribution files; build only a private copy.
    source = output.parent / 'release-source'
    shutil.copytree(adapter / 'vendor/abba_family', source)
    recipe = output.parent / 'recipe'
    recipe.mkdir()
    exports = recipe / 'exports.map'
    exports.write_text('{ global: tscb_*; tsbench_core_*; local: *; };\n')
    recipe.joinpath('CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.18)
project(tsbench_abba LANGUAGES C CXX)
find_package(Threads REQUIRED)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory("{source}" standalone EXCLUDE_FROM_ALL)
add_library(tsbench_binding SHARED "{adapter / 'native/binding.cc'}")
target_include_directories(tsbench_binding PRIVATE "{root / 'native/include'}" "{source / 'vendor/zlib'}")
target_link_libraries(tsbench_binding PRIVATE abba_family_static af_ckmeans af_byte_zlib af_byte_zstd af_byte_bz2 af_lzma Threads::Threads)
target_compile_definitions(tsbench_binding PRIVATE AF_KEY="{key}")
target_compile_options(tsbench_binding PRIVATE -Wall -Wextra -Wpedantic)
target_link_options(tsbench_binding PRIVATE -Wl,-z,defs -Wl,-Bsymbolic-functions -Wl,--exclude-libs,ALL "-Wl,--version-script={exports}")
set_target_properties(tsbench_binding PROPERTIES OUTPUT_NAME tscb_{key} LIBRARY_OUTPUT_DIRECTORY "{output.parent}")
''')
    _run(['cmake','-S',str(recipe),'-B',str(output.parent / 'cmake'),'-DCMAKE_BUILD_TYPE=Release',
          '-DCMAKE_CXX_FLAGS=-fno-fast-math -ffp-contract=off','-DCMAKE_C_FLAGS=-fno-fast-math -ffp-contract=off'])
    _run(['cmake','--build',str(output.parent / 'cmake'),'--target','tsbench_binding','--parallel','2'])


def _cameo_build(root: Path, key: str, output: Path) -> None:
    """Build one isolated numerical closure for the ten canonical bindings.

    Shared products are content-addressed, locked, and checked against every
    actual compiler input, toolchain and archive before reuse. No system BLAS.
    """
    import fcntl
    adapter = root / 'adapters/cameo_family'
    lock = json.loads((adapter / 'FROZEN_SOURCES.json').read_text())
    for entry in lock['files']:
        if sha(root / entry['path']) != entry['sha256']:
            raise Unavailable(f'frozen CAMEO source changed: {entry["path"]}', stage='build')
    source_identity = [x for x in _source_files(root,key) if not x['path'].startswith('registry/codecs/')]
    compiler_identity = {}
    for name in (os.environ.get('CC','cc'),os.environ.get('CXX','c++'),'cmake','make'):
        path = Path(shutil.which(name)).resolve()
        compiler_identity[str(path)] = sha(path)
    identity = hashlib.sha256(json.dumps([source_identity,compiler_identity,CAMEO_FAMILY],sort_keys=True).encode()).hexdigest()
    common = output.parents[2] / 'cameo-family-cache' / identity
    common.parent.mkdir(parents=True,exist_ok=True)
    with (common.parent / (identity+'.lock')).open('w') as mutex:
        fcntl.flock(mutex,fcntl.LOCK_EX)
        record_path = common / 'closure.json'
        record = json.loads(record_path.read_text()) if record_path.is_file() else {}
        entries = record.get('files',[])
        valid = bool(entries) and all(Path(x['path']).is_file() and sha(Path(x['path']))==x['sha256'] for x in entries)
        if not valid:
            if common.exists():
                shutil.rmtree(common)
            common.mkdir()
            source = common / 'release-source'
            shutil.copytree(adapter / 'vendor/cameo_family',source)
            recipe = common / 'recipe'
            recipe.mkdir()
            exports = recipe / 'exports.map'
            exports.write_text('{ global: tscb_*; tsbench_core_*; local: *; };\n')
            lines = [f'''cmake_minimum_required(VERSION 3.18)
project(tsbench_cameo LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory("{source}" standalone EXCLUDE_FROM_ALL)
''']
            for name,kind in CAMEO_FAMILY.items():
                target = name.replace('-','_')
                lines.append(f'''add_library(tscb_{target} SHARED "{adapter / 'native/binding.cc'}")
target_include_directories(tscb_{target} PRIVATE "{root / 'native/include'}" "{source / 'tools'}")
target_link_libraries(tscb_{target} PRIVATE cameo_family_static)
target_compile_definitions(tscb_{target} PRIVATE CF_KEY="{name}" CF_KIND={kind})
target_compile_options(tscb_{target} PRIVATE -Wall -Wextra -Wpedantic)
target_link_options(tscb_{target} PRIVATE -Wl,-z,defs -Wl,-Bsymbolic-functions -Wl,--exclude-libs,ALL "-Wl,--version-script={exports}")
set_target_properties(tscb_{target} PROPERTIES LIBRARY_OUTPUT_DIRECTORY "{common / 'lib'}")
''')
            recipe.joinpath('CMakeLists.txt').write_text('\n'.join(lines))
            _run(['cmake','-S',str(recipe),'-B',str(common/'cmake'),'-DCMAKE_BUILD_TYPE=Release',
                  '-DCMAKE_C_COMPILER='+os.environ.get('CC','cc'),'-DCMAKE_CXX_COMPILER='+os.environ.get('CXX','c++'),
                  '-DCMAKE_CXX_FLAGS=-fno-fast-math -ffp-contract=off','-DCMAKE_C_FLAGS=-fno-fast-math -ffp-contract=off'])
            targets = ['tscb_'+name.replace('-','_') for name in CAMEO_FAMILY]
            _run(['cmake','--build',str(common/'cmake'),'--target',*targets,'--parallel','2'])
            entries = _compiled_dependencies(root,common)
            products = [*sorted((common/'lib').glob('*.so')),*sorted((common/'cmake').rglob('*.a')),
                        recipe/'CMakeLists.txt',exports]
            entries += [{'path':str(p),'sha256':sha(p)} for p in products]
            compilers = {os.environ.get('CC','cc'):{'path':shutil.which(os.environ.get('CC','cc'))},
                         os.environ.get('CXX','c++'):{'path':shutil.which(os.environ.get('CXX','c++'))}}
            entries += _toolchain_dependencies(compilers)
            record = {'identity':identity,'files':entries,'commands':recipes.COMMANDS.copy()}
            record_path.write_text(json.dumps(record,indent=2)+'\n')
        else:
            recipes.COMMANDS.append({'shared_family_build_record':str(record_path),'sha256':sha(record_path)})
        shutil.copy2(common/'lib'/output.name,output)
        (output.parent/'compiled-family.json').write_text(json.dumps(record['files'],indent=2)+'\n')


def _simd_build(root: Path, output: Path) -> None:
    adapter = root / 'adapters/simdcomp'
    lock = json.loads((adapter / 'SOURCE_LOCK.json').read_text())
    for record in lock['files']:
        if sha(root / record['path']) != record['sha256']:
            raise Unavailable(f'frozen SIMDComp source changed: {record["path"]}', stage='build')
    source = output.parent / 'patched-source'
    shutil.copytree(adapter / 'vendor/simdcomp', source)
    patches = [*sorted((adapter / 'patches').glob('*.patch')), adapter / 'patches/avx2/0001-zero-width-unpack-byte-count.patch']
    for patch in patches:
        _run(['patch','--batch','--forward','-p1','-d',str(source),'-i',str(patch)])
    baseline = ['-march=x86-64','-mno-ssse3','-mno-sse4.1','-mno-avx','-mno-avx2','-mno-avx512f','-fno-tree-vectorize','-fno-tree-slp-vectorize']
    sse = ['-march=x86-64','-msse4.1','-mno-avx','-mno-avx2','-mno-avx512f']
    avx = ['-march=x86-64','-mavx2','-mno-avx512f']
    units = [('shim', adapter / 'native/tscb_simdcomp.c', baseline)]
    units += [(name,source / 'src' / (name+'.c'),sse) for name in ('simdbitpacking','simdintegratedbitpacking','simdfor','simdcomputil','simdpackedselect','simdpackedsearch')]
    units += [('avxbitpacking',source / 'src/avxbitpacking.c',avx),('avx2_bridge',adapter / 'native/avx2_bridge.c',avx)]
    objects = []
    for name, unit, isa in units:
        obj = output.parent / (name+'.o')
        _run([os.environ.get('CC','cc'),'-std=c11','-fPIC','-Wall','-Wextra','-Werror','-O3','-DNDEBUG',*isa,
              '-I',str(root / 'native/include'),'-I',str(source / 'include'),'-MD','-MF',str(obj.with_suffix('.d')),
              '-c',str(unit),'-o',str(obj)])
        objects.append(str(obj))
    direct = adapter / 'native/direct_core.cc'
    obj = output.parent / 'direct_core.o'
    _run([os.environ.get('CXX','c++'),'-std=c++17','-fPIC','-Wall','-Wextra','-Werror','-O3','-DNDEBUG',*baseline,
          '-I',str(root / 'native/include'),'-I',str(source / 'include'),'-MD','-MF',str(obj.with_suffix('.d')),
          '-c',str(direct),'-o',str(obj)])
    objects.append(str(obj))
    _run([os.environ.get('CXX','c++'),'-shared','-Wl,-z,defs','-Wl,-Bsymbolic-functions',*objects,'-o',str(output)])


def _command(key: str, output: Path) -> list[str]:
    if key == 'gorilla-prometheus-xor':
        adapter = recipes.PROJECT_ROOT / 'adapters/gorilla_prometheus_xor'
        lock = json.loads((adapter / 'FROZEN_SOURCES.json').read_text())
        for record in lock['files']:
            path = recipes.PROJECT_ROOT / record['path']
            if sha(path) != record['sha256']:
                raise Unavailable(f'frozen Gorilla source changed: {path}', stage='build')
        core = adapter / 'vendor/gorilla'
        return [os.environ.get('CXX', 'c++'), '-std=c++17', '-O3', '-DNDEBUG',
                '-fPIC', '-shared', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
                '-fno-fast-math', '-ffp-contract=off', '-DGORILLA_HAS_OPTIMIZED=1',
                '-I', str(recipes.PROJECT_ROOT / 'native/include'), '-I', str(core / 'include'),
                str(adapter / 'native/tscb_gorilla.cc'), str(core / 'src/canonical/gorilla.cpp'),
                str(core / 'src/optimized/bitops.cpp'), '-Wl,-z,defs', '-Wl,-Bsymbolic-functions',
                '-o', str(output)]
    mapping = {
        'lz4-frame': recipes._lz4_command, 'zstd-frame': recipes._zstd_command,
        'snappy-raw': recipes._snappy_command, 'lzsse2-raw': recipes._lzsse2_command,
        'lzsse8-raw': recipes._lzsse8_command, 'brotli-stream': recipes._brotli_command,
        'deflate-zlib': recipes._deflate_zlib_command, 'bzip2-stream': recipes._bzip2_command,
        'xz-stream': recipes._xz_command, 'lzss-raw': recipes._lzss_command,
        'lzss-dipperstein-c': recipes._lzss_dipperstein_command, 'zfp-accuracy-1d': recipes._zfp_command,
    }
    if key in mapping:
        result = mapping[key](output, 'release')
    elif key in ('huff0','fse'):
        result = recipes._entropy_command(output,'release',key)
    elif key in recipes.SPRINTZ_FAMILY:
        result = recipes._sprintz_family_command(output,'release',key)
    elif key in recipes.CHIMP_FAMILY:
        result = recipes._chimp_family_command(output,'release',key)
    elif key in ('alp','alp-rd'):
        result = recipes._alp_command(output,'release',key)
    elif key.startswith('serf-'):
        result = recipes._serf_command(output,'release',key)
    elif key in ('neats-lossless-i64','leats-lossless-i64'):
        result = recipes._neats_command(output,'release',key)
    else:
        result = recipes._rewrite_lossless_command(output,'release',key)
    command = result[0] if isinstance(result,tuple) else result
    folder = recipes.PROJECT_ROOT / 'adapters' / _FOLDERS.get(key,key.replace('-','_')) / 'native'
    direct = folder / 'direct_core.cc'
    if direct.is_file():
        command.insert(command.index('-o'), str(direct))
    return command


def build_codec(root: str | Path, key: str, *, force: bool = False, build_root=None) -> dict:
    root = Path(root).resolve()
    spec = Registry(root).get(key)
    spec.require_enabled()
    key = spec.key
    if key == 'raw-store':
        return {'status':'ok','codec':key,'build_id':'builtin:raw-store-v1','artifact':None}
    sources = _source_files(root,key)
    compiler_names = [os.environ.get('CC','cc'),os.environ.get('CXX','c++'),'clang++']
    compilers = {}
    for name in compiler_names:
        executable = shutil.which(name)
        if executable:
            done = subprocess.run([executable,'--version'],capture_output=True,text=True,check=True)
            compilers[name] = {'path':str(Path(executable).resolve()),'sha256':sha(Path(executable).resolve()),'version':done.stdout.splitlines()[0]}
    identity = {'codec':key,'profile':'release','sources':sources,'compilers':compilers,'env':{name:os.environ.get(name) for name in ['CC','CXX']},'recipe_version':1}
    identity_hash = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    base = _build_base(root,build_root)
    output = base / identity_hash / key / ('libtscb_' + key.replace('-', '_') + '.so')
    record_path = output.parent / 'build.json'
    index_path = base / (key + '.index.json')
    if not output.resolve().is_relative_to(root):
        raise Unavailable('native build_root must stay inside the asset project',stage='build')
    if not force and output.is_file() and record_path.is_file():
        previous = json.loads(record_path.read_text())
        if previous.get('identity_sha256') == identity_hash and previous.get('artifact_sha256') == sha(output):
            closure = previous.get('compiled_source_closure',[])
            verified = [*previous.get('runtime_dependencies',[]),*closure,*previous.get('toolchain_files',[])]
            if closure and all(Path(entry['path']).is_file() and sha(Path(entry['path'])) == entry['sha256'] for entry in verified):
                index_path.write_text(json.dumps({'build_id':previous['build_id'],'artifact':str(output),'build_record':str(record_path)},indent=2)+'\n')
                return previous
    if output.parent.exists():
        shutil.rmtree(output.parent)
    output.parent.mkdir(parents=True)
    recipes.PROJECT_ROOT = root
    recipes.COMMANDS.clear()
    try:
        if key in CAMEO_FAMILY:
            _cameo_build(root,key,output)
        elif key in _ABBA_FAMILY:
            _abba_build(root,key,output)
        elif key in _RW:
            _rw_build(root,key,output)
        elif key == 'simdcomp-u32':
            _simd_build(root,output)
        else:
            _compile_native(_command(key,output),output)
        listing = _run(['ldd',str(output)])
        if 'not found' in listing:
            raise RuntimeError('unresolved runtime dependency: '+listing)
        runtime = [Path(value).resolve() for value in re.findall(r'(?:=>\s*)?(/[^\s]+)\s+\(0x',listing)]
        record = {'schema_version':'tsbench.build.v1','status':'ok','codec':key,
                  'identity_sha256':identity_hash,'artifact':str(output.relative_to(root)),
                  'artifact_sha256':sha(output),'build_id':'sha256:'+identity_hash,
                  **identity,'commands':recipes.COMMANDS.copy(),
                  'runtime_dependencies':[{'path':str(path),'sha256':sha(path)} for path in sorted(set(runtime))],
                  'ldd':listing, 'dependency_capture':'ACTUAL_PER_TU_MD',
                  'compiled_source_closure':_compiled_dependencies(root,output.parent),
                  'toolchain_files':_toolchain_dependencies(compilers)}
        record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        index_path.write_text(json.dumps({'build_id':record['build_id'],'artifact':str(output),'build_record':str(record_path)},indent=2)+'\n')
        return record
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        record_path.write_text(json.dumps({'status':'unavailable','codec':key,'error':str(error),'commands':recipes.COMMANDS.copy()},indent=2)+'\n')
        raise Unavailable(f'{key}: native build failed: {error}',stage='build') from error


def build_all(root: str | Path, keys: list[str] | None = None, *, force: bool = False, build_root=None) -> list[dict]:
    """Serial recipes; CMake recipes may use two compiler workers at most."""
    root = Path(root).resolve()
    if keys is None:
        cards = root / 'registry/codecs'
        if not cards.is_dir():
            raise Unavailable(f'codec registry missing: {cards}; build --all requires a native asset checkout', stage='build')
        keys = [spec.key for spec in Registry(root).list(include_reference=False)]
    if not keys:
        raise Unavailable('no native codecs selected; an empty build is not a successful build', stage='build')
    result = []
    for key in keys:
        try:
            record = build_codec(root,key,force=force,build_root=build_root)
        except Unavailable as error:
            record = {'codec':key,'status':'unavailable','error':str(error)}
        result.append(record)
    return result
