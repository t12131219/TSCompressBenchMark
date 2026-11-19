"""Same-run Huff0 condition: distinct, recipe-matched ON/OFF ELF closures."""
from pathlib import PurePosixPath
import re

from ..assets import digest, load_json, local_file, require
from ..recovery import check_recovery, plan_recovery
from .huff0 import PLUGIN
from .huff0_portable import BINARIES, PLUGIN_DIR, RECIPE, SOURCE, prove_build_pair
from .native_conditions import CONDITIONS

SUITE = 'extended-v20'
TOOL = 'huff0-portable-direct'
DIRECTORY = 'huff0-portable-recovery'
OPERATION = 'portable-decode'
KEY = 'huff0_bmi2_control'
PREDICATE = 'huff0_dynamic_bmi2_and_cpu_available'
CHECK, BUNDLE, SELECTOR, CRITERIA = CONDITIONS[(29,PLUGIN,PREDICATE)]
SOURCES = ('src/tsbench/planner/huff0_bmi2.py','src/tsbench/planner/huff0_portable.py',
           'src/tsbench/recovery.py','src/tsbench/supervisor/isolated_worker.py',SOURCE)


def supports_condition(ob):
    return (ob['kind'],ob['selection'],ob['route'],ob['check'])==('conditional',29,PLUGIN,CHECK)


def condition_slots(ob, slots):
    case=ob['condition_case']
    require((case['predicate'],case['bundle_key'],case['selector'],case['criteria'])==
            (PREDICATE,BUNDLE,SELECTOR,CRITERIA),'Huff0 BMI2 condition definition differs')
    ids = [s['product_slot'] for s in slots if s.get(KEY) is True]
    require(len(ids)==9,'Huff0 BMI2 requires all retained FEC1 and ETB1 products')
    return sorted(ids)


def _primary_build(decoder, tool):
    source = PurePosixPath(decoder['files'][decoder['tools'][tool]]['source'])
    require(source.parent.name==PLUGIN_DIR.name and source.parent.parent.name=='codecs' and
            source.parent.parent.parent.name=='plugins', 'Huff0 primary build root differs')
    return source.parents[3]


def plan_control(root, primary_decoder, tool, directory, archive):
    primary_dir = _primary_build(primary_decoder,tool)
    primary = local_file(root,(primary_dir/'CMakeCache.txt').as_posix()).parent
    portable = local_file(root,(PurePosixPath(directory)/'CMakeCache.txt').as_posix()).parent
    recipe = prove_build_pair(root,primary,portable,archive)
    relative = portable.relative_to(root).as_posix()
    library, executable = [{'path':f'{relative}/{p}','sha256':digest(local_file(root,f'{relative}/{p}'))} for p in BINARIES]
    body = {'schema':'bmk.huff0-unified-bmi2/1','build_dir':relative,'archive_sha256':archive,
            'source_manifest_sha256':digest(local_file(root,SOURCE)),
            'normalized_build_recipe':recipe,'library':library,'executable':executable,
            'decoder':plan_recovery(root,None,{},tools={TOOL:executable},libraries=[library])}
    check_control(body,primary_decoder,tool,archive,body['source_manifest_sha256'])
    return body


def check_control(body, primary, tool, archive, manifest):
    require(isinstance(body,dict) and set(body)=={'schema','build_dir','archive_sha256','source_manifest_sha256',
            'normalized_build_recipe','library','executable','decoder'} and body['schema']=='bmk.huff0-unified-bmi2/1' and
            body['archive_sha256']==archive and body['source_manifest_sha256']==manifest,
            'Huff0 portable source identity differs')
    directory = PurePosixPath(body['build_dir'])
    origin = _primary_build(primary,tool)
    require(not directory.is_absolute() and '..' not in directory.parts and str(directory) not in ('','.','/') and
            not directory.is_relative_to(origin) and not origin.is_relative_to(directory), 'Huff0 portable build path overlaps')
    recipe = body['normalized_build_recipe']
    require(set(recipe)=={f'{p}/{f}' for p in RECIPE for f in ('flags.make','link.txt')} and
            all(re.fullmatch('[a-f0-9]{64}',v) for v in recipe.values()), 'Huff0 normalized build recipe differs')
    for key,path in zip(('library','executable'),BINARIES,strict=True):
        ref = body[key]
        require(set(ref)=={'path','sha256'} and ref['path']==str(directory/path), 'Huff0 portable recipe output moved')
    scope = body['decoder']
    check_recovery(scope,None,{},tools={TOOL:body['executable']},libraries=[body['library']])
    program = scope['files'][scope['tools'][TOOL]]
    lib = 'lib/libreference.so'
    require('libreference.so' in program['needed'] and
            primary['files'][lib]['sha256']!=scope['files'][lib]['sha256'] and
            primary['files'][primary['tools'][tool]]['sha256']!=program['sha256'] and
            all(row==primary['files'][name] for name,row in scope['files'].items() if row['origin']=='system'),
            'Huff0 portable runtime is not a distinct recipe-matched closure')
