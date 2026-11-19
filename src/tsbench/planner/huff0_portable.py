"""Bind an explicit Huff0 portable decode control to the primary probe's artifacts."""
from pathlib import Path
import re

from ..assets import content_id, digest, load_json, local_file, require

TEST = 'tsbench.control.huff0-portable-decode'
REPORT = 'huff0-portable-decode.json'
DRIVER = 'tests/isolation/huff0_portable_decode.py'
PLUGIN_DIR = Path('plugins/codecs/huff0-reference')
BINARIES = tuple((PLUGIN_DIR / name).as_posix() for name in ('libreference.so', 'tsbench_huff0_control'))
SOURCE = 'third_party/provenance/FiniteStateEntropy/source-manifest.json'
RECIPE = {
    (PLUGIN_DIR / 'upstream/CMakeFiles/reference_core.dir').as_posix(): ('DYNAMIC_BMI2', 'ENTROPY_DYNAMIC_BMI2'),
    (PLUGIN_DIR / 'upstream/CMakeFiles/reference.dir').as_posix(): ('ENTROPY_DYNAMIC_BMI2',),
    'CMakeFiles/tsbench_huff0_control.dir': ('TSBENCH_ENTROPY_DYNAMIC_BMI2',),
}


def _build_recipe(build, root, expected):
    cache = local_file(build, 'CMakeCache.txt').read_text()
    require(f'CMAKE_HOME_DIRECTORY:INTERNAL={root}\n' in cache and
            f'ENTROPY_DYNAMIC_BMI2:BOOL={"ON" if expected else "OFF"}\n' in cache,
            'Huff0 control requires distinct dynamic ON and portable OFF builds of this project')
    normalized = {}
    for directory, defines in RECIPE.items():
        for name in ('flags.make','link.txt'):
            relative = f'{directory}/{name}'
            text = local_file(build,relative).read_text()
            text = text.replace(str(build),'${BUILD}').replace(str(root),'${PROJECT}')
            if name == 'flags.make':
                for key in defines:
                    pattern = rf'(?<!\S)-D{key}={expected}(?!\S)'
                    text, count = re.subn(pattern,f'-D{key}=${{BMI2}}',text)
                    require(count==1,f'Huff0 build does not prove the requested {key}={expected}: {relative}')
            normalized[relative] = content_id(text)
    return normalized


def prove_build_pair(root, primary, portable, archive_sha256):
    require(portable != primary and not portable.is_relative_to(primary) and not primary.is_relative_to(portable)
            and portable != root and portable.is_dir(), 'Huff0 portable needs a separate configured build directory')
    source_lock = load_json(local_file(root,SOURCE))
    require(source_lock['sha256']==archive_sha256, 'Huff0 portable archive differs from primary')
    for build in (primary,portable):
        for entry in source_lock['files']:
            src = (PLUGIN_DIR / 'source' / entry['path']).as_posix()
            require(digest(local_file(build,src))==entry['sha256'], f'Huff0 extracted build source differs: {src}')
    norm = _build_recipe(primary,root,1)
    require(norm==_build_recipe(portable,root,0), 'Huff0 primary and portable build recipes differ beyond BMI2')
    return norm


def bind_portable_control(root, primary, portable, primary_slot, huff0, archive_sha256, assets, file_ref):
    norm = prove_build_pair(root,primary,portable,archive_sha256)
    command = [{'python':True},{'literal':'-I'},{'literal':'-B'}]
    for label, base, relative in [('project',root,DRIVER), *(('huff0_portable',portable,p) for p in BINARIES)]:
        key = f'{label}:{relative}'
        assets[key] = {'root':label,**file_ref(base,relative)}
        command.append({'asset':key})
    command.extend(({'input_slot':primary_slot['slot_id']},{'output':REPORT}))
    slot = {'test':TEST,'command':command,'timeout_seconds':60,'skip_returncode':None,
            'evidence':[REPORT],'smoke_export':False,'requires_slot':primary_slot['slot_id']}
    slot = {'slot_id':content_id(slot),**slot}
    body = {'schema':'bmk.huff0-portable-control-plan/1','bundle_id':huff0['bundle_id'],
            'archive_sha256':archive_sha256,'source_manifest_sha256':digest(local_file(root,SOURCE)),
            'primary_slot_id':primary_slot['slot_id'],'control_slot_id':slot['slot_id'],
            'test':TEST,'evidence_path':REPORT,'normalized_build_recipe':norm,
            'comparison':'same_run_primary_fec1_payload_etb1_blocks_and_models'}
    return slot, {**body,'control_id':content_id(body)}
