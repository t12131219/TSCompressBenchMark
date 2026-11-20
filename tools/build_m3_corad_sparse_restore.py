#!/usr/bin/env python3
"""Widen the diagnostic CORAD restore control's input buffer, not its codec."""
from argparse import ArgumentParser
from pathlib import Path
import subprocess

from m3_corad_sparse_development import ROOT, SCHEMA, TOOL, check, ref
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, require
from tsbench.recovery import plan_recovery

CAP = '#define FRAME_CAP (256u * 1024u)'
WIDE_CAP = '#define FRAME_CAP (512u * 1024u)'


def widened(text, encoder_text):
    require(text.count(CAP) == 1 and encoder_text.count(WIDE_CAP) == 1,
            'CORAD control does not have the expected input/output buffer difference')
    return text.replace(CAP, WIDE_CAP)


def build(base_file, output):
    base = load_json(base_file)
    body = {k:v for k,v in base.items() if k!='build_id'}
    require(base['schema']==SCHEMA+'-build' and base['build_id']==content_id(body)
            and 'restore_control' not in base, 'expected the original sparse-development build')
    original = base['restore']
    tool = original['tools'][TOOL]
    library = original['files']['lib/libcorad_c.so']
    source = check(ROOT,base['control_source'])
    encoder = check(ROOT,base['derived'])
    header = check(ROOT,base['header'])
    shared = check(ROOT,{'path':library['source'],'sha256':library['sha256'],'bytes':library['bytes']})
    require(output.is_relative_to(ROOT/'build'), 'CORAD restore build escaped workspace')
    output.mkdir(parents=True, exist_ok=False)
    derived = output/'corad_sparse_restore.c'
    derived.write_text(widened(source.read_text(), encoder.read_text()))
    obj = output/Path(tool).name
    subprocess.run(['/usr/bin/cc','-std=c11','-O2','-fno-fast-math','-ffp-contract=off','-Wall','-Wextra','-Werror',
                    '-I',str(header.parent),str(derived),str(shared),'-Wl,-rpath,$ORIGIN','-o',str(obj)],check=True)
    restore = plan_recovery(ROOT,{},(),tools={TOOL:{'path':obj.relative_to(ROOT).as_posix(),'sha256':ref(ROOT,obj)['sha256']}},
                            libraries=[{'path':library['source'],'sha256':library['sha256']}])
    require(restore['tools']==original['tools'] and restore['files'][tool]['needed']==original['files'][tool]['needed'] and
            {k:v for k,v in restore['files'].items() if k!=tool}=={k:v for k,v in original['files'].items() if k!=tool},
            'wider CORAD control changed the native restore dependency closure')
    body.update(restore=restore,restore_control={'source':ref(ROOT,derived),'builder':ref(ROOT,Path(__file__).resolve()),
                                                'base_build':ref(ROOT,base_file),'frame_buffer_bytes':512 << 10})
    write_new(output/'build-lock.json',{**body,'build_id':content_id(body)})


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    try:
        build(a.base.resolve(strict=True),a.out.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        p.exit(1,f'{exc}\n')
