"""Build the frozen official cuSZp kernels and checked GPU adapter; no GPU work."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def build(root=None, *, build_root=None, architecture=75, nvcc=None, host_compiler=None):
    root=Path(root or Path(__file__).resolve().parents[3]).resolve()
    base=Path(build_root or root/'build/tsbench-gpu').resolve()
    adapter=root/'adapters/cuszp'
    lock=json.loads((adapter/'SOURCE_LOCK.json').read_text())
    for entry in lock['files']:
        if sha(root/entry['path'])!=entry['sha256']:
            raise RuntimeError('frozen cuSZp source changed: '+entry['path'])
    nvcc=Path(nvcc or shutil.which('nvcc') or '/usr/local/cuda-11.8/bin/nvcc').resolve(strict=True)
    host=Path(host_compiler or shutil.which('g++-11') or shutil.which('g++')).resolve(strict=True)
    if type(architecture) is not int or architecture not in {60,61,62,70,75,80,86,89,90}:
        raise ValueError('explicit supported compute architecture required')
    files=[p for p in sorted(adapter.rglob('*')) if p.is_file()]
    files.extend([Path(__file__),root/'benchmark/src/tsbench/bridges/cuszp.py',
                  root/'registry/gpu/cuszp-fixed-1d.json'])
    source=[{'path':str(p.relative_to(root)),'sha256':sha(p),'nbytes':p.stat().st_size} for p in files]
    compiler={'nvcc':{'path':str(nvcc),'sha256':sha(nvcc),'version':subprocess.check_output([str(nvcc),'--version'],text=True)},
              'host':{'path':str(host),'sha256':sha(host),'version':subprocess.check_output([str(host),'--version'],text=True)}}
    toolkit=nvcc.parent.parent
    toolchain=[nvcc,host]
    for p in [toolkit/'bin/ptxas',toolkit/'bin/cudafe++',toolkit/'nvvm/bin/cicc',
              toolkit/'bin/fatbinary',toolkit/'bin/nvlink',toolkit/'version.json',
              toolkit/'nvvm/libdevice/libdevice.10.bc',
              toolkit/'targets/x86_64-linux/lib/libcudart_static.a',
              toolkit/'targets/x86_64-linux/lib/libcudadevrt.a']:
        if p.is_file():toolchain.append(p)
    for name in ['cc1plus','as','collect2','ld']:
        p=subprocess.check_output([str(host),'-print-prog-name='+name],text=True).strip()
        p=shutil.which(p) or p
        if Path(p).is_file():toolchain.append(Path(p))
    for name in ['crtbeginS.o','crtendS.o','crti.o','crtn.o','libgcc.a','libgcc_s.so',
                 'libstdc++.so','libm.so','libc.so','librt.a','libpthread.a','libdl.a']:
        p=subprocess.check_output([str(host),'-print-file-name='+name],text=True).strip()
        if Path(p).is_file():toolchain.append(Path(p))
    toolchain_records=[{'path':str(p.resolve()),'sha256':sha(p)} for p in sorted(set(toolchain))]
    identity={'schema':'tsbench.cuszp-build-identity/1','sources':source,'compilers':compiler,'architecture':architecture,
              'flags':['-std=c++17','-O3','-fmad=false','-Xcompiler=-fPIC,-fno-fast-math,-ffp-contract=off'],
              'link_flags':['-shared','-Xlinker=-z,defs','-Xlinker=-t'],
              'toolchain_files':toolchain_records,'upstream_commit':lock['commit'],'backend':'CUDA','exported_mode':'1D_FIXED'}
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    folder=base/digest/'cuszp';artifact=folder/'libtsbench_cuszp_gpu.so';record=folder/'build.json'
    index=base/'cuszp-fixed-1d.index.json'
    if record.exists():
        old=json.loads(record.read_text())
        if old['identity_sha256']!=digest or sha(artifact)!=old['artifact_sha256']:
            raise RuntimeError('existing immutable GPU build differs')
        for entry in old['compiled_dependencies']+old['toolchain_files']+old['link_dependencies']+old['runtime_dependencies']:
            if sha(entry['path'])!=entry['sha256']:
                raise RuntimeError('cached GPU dependency changed: '+entry['path'])
        index.write_text(json.dumps({'artifact':str(artifact),'build_record':str(record),'identity_sha256':digest},indent=2)+'\n')
        return artifact
    folder.mkdir(parents=True,exist_ok=False)
    commands=[];logs=[];objects=[]
    vendor=adapter/'vendor/cuszp'
    units=[adapter/'native/cuszp_gpu.cu',vendor/'src/cuSZp_kernels_1D_f32.cu',vendor/'src/cuSZp_kernels_1D_f64.cu']
    flags=['-std=c++17','-O3','-fmad=false','-Xcompiler=-fPIC,-fno-fast-math,-ffp-contract=off',
           '-ccbin',str(host),'-gencode',f'arch=compute_{architecture},code=sm_{architecture}',
           '-gencode',f'arch=compute_{architecture},code=compute_{architecture}',
           '-I',str(adapter/'native'),'-I',str(vendor/'include/cuSZp')]
    for i,unit in enumerate(units):
        obj=folder/f'{i}-{unit.stem}.o';dep=obj.with_suffix('.d')
        command=[str(nvcc),*flags,'-MD','-MF',str(dep),'-c',str(unit),'-o',str(obj)]
        commands.append(command)
        done=subprocess.run(command,cwd=root,capture_output=True,text=True)
        logs.append({'command':command,'returncode':done.returncode,'stdout':done.stdout,'stderr':done.stderr})
        if done.returncode:
            (folder/'failed_build.json').write_text(json.dumps({'identity':identity,'logs':logs},indent=2)+'\n')
            raise RuntimeError('cuSZp CUDA compilation failed: '+done.stderr[-3000:])
        objects.append(str(obj))
    command=[str(nvcc),'-ccbin',str(host),'-shared',*objects,'-Xlinker=-z,defs','-Xlinker=-t','-o',str(artifact)]
    commands.append(command)
    done=subprocess.run(command,cwd=root,capture_output=True,text=True)
    logs.append({'command':command,'returncode':done.returncode,'stdout':done.stdout,'stderr':done.stderr})
    if done.returncode:
        (folder/'failed_build.json').write_text(json.dumps({'identity':identity,'logs':logs},indent=2)+'\n')
        raise RuntimeError('cuSZp CUDA link failed: '+done.stderr[-3000:])
    link_files=set()
    for name in (done.stdout+'\n'+done.stderr).splitlines():
        p=Path(name.strip())
        if p.is_absolute() and p.is_file():link_files.add(p.resolve())
    dependencies=set()
    for p in folder.glob('*.d'):
        text=p.read_text().replace('\\\n',' ')
        for name in shlex.split(text.split(':',1)[1]):
            p=Path(name);dependencies.add((p if p.is_absolute() else root/p).resolve(strict=True))
    runtime=subprocess.check_output(['ldd',str(artifact)],text=True)
    libraries=[]
    for line in runtime.splitlines():
        parts=line.strip().split()
        name=parts[2] if '=>' in parts and len(parts)>2 else parts[0] if parts else ''
        if name.startswith('/') and Path(name).is_file():libraries.append({'path':name,'resolved_path':str(Path(name).resolve()),'sha256':sha(name)})
    data={'schema':'tsbench.cuszp-build/1','identity_sha256':digest,'identity':identity,
          'artifact':str(artifact),'artifact_sha256':sha(artifact),'commands':commands,'logs':logs,
          'compiled_dependencies':[{'path':str(p),'sha256':sha(p)} for p in sorted(dependencies)],
          'toolchain_files':toolchain_records,
          'link_dependencies':[{'path':str(p),'sha256':sha(p)} for p in sorted(link_files)],
          'runtime_dependencies':libraries,'ldd':runtime,'gpu_work_executed':False}
    record.write_text(json.dumps(data,indent=2)+'\n')
    index.write_text(json.dumps({'artifact':str(artifact),'build_record':str(record),'identity_sha256':digest},indent=2)+'\n')
    return artifact


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path);p.add_argument('--build-root',type=Path);p.add_argument('--architecture',type=int,default=75)
    a=p.parse_args();print(build(a.root,build_root=a.build_root,architecture=a.architecture))


if __name__=='__main__':main()
