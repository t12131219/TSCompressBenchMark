#!/usr/bin/env python3
"""Record actual compiler commands, included headers, ELFs and loaded libraries."""
import hashlib,json,os,pathlib,re,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def cmd(args):
    r=subprocess.run(args,capture_output=True,text=True)
    return {'argv':[str(x) for x in args],'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
def main():
    report={'standard':'v3.0','route':'NATIVE_PORT','source_commit':'31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce','profiles':{},'tools':{},'runtime_instrumentation':'project core and wrapper instrumented in sanitizer builds; system libc, libstdc++ and QEMU not instrumented','host':cmd(['lscpu'])}
    for tool in ['/usr/bin/g++','/usr/bin/clang++','/usr/bin/cmake','/usr/bin/ld','/home/fzg/anaconda3/bin/python3']:
        p=pathlib.Path(tool).resolve();report['tools'][tool]={'resolved':str(p),'sha256':sha(p),'version':cmd([tool,'--version'])}
    for name in ['release','avx2','clang','asan','asan-avx2','tsan','fuzz','arm64']:
        build=ROOT/'build'/name
        if not build.exists():continue
        commands=json.loads((build/'compile_commands.json').read_text())
        headers={}
        for dep in build.rglob('*.o.d'):
            text=dep.read_text().replace('\\\n',' ');parts=text.split(':',1)[1].split()
            for path in parts:
                p=pathlib.Path(path)
                if not p.is_absolute():p=build/p
                if p.is_file():headers[str(p.resolve())]=sha(p.resolve())
        binaries={}
        for f in ['libalp_port.so','alp_cli','alp_tests','c_consumer','allocation_failure','alp_fuzz','alp_upstream_oracle']:
            p=build/f
            if p.exists():
                b={'sha256':sha(p),'bytes':p.stat().st_size,'elf':cmd(['readelf','-h',str(p)]),'needed':cmd(['readelf','-d',str(p)])}
                if name!='arm64':
                    loaded=cmd(['ldd',str(p)]);b['ldd']=loaded;b['loaded_files']={}
                    for line in loaded['stdout'].splitlines():
                        m=re.search(r'(?:=>\s+)?(/[^\s]+)',line)
                        if m and pathlib.Path(m[1]).is_file():b['loaded_files'][m[1]]=sha(pathlib.Path(m[1]).resolve())
                binaries[f]=b
        report['profiles'][name]={'commands':commands,'headers_and_TUs':headers,'binaries':binaries,'cmake_cache_sha256':sha(build/'CMakeCache.txt')}
    arm=os.environ.get('ALP_ARM_TOOLCHAIN')
    if arm:
        a=pathlib.Path(arm);report['arm_toolchain']={'root':str(a),'files':{}}
        for sub in ['usr/aarch64-linux-gnu/lib','usr/bin','usr/lib/gcc-cross/aarch64-linux-gnu/11']:
            for f in (a/sub).glob('*'):
                if f.is_file():report['arm_toolchain']['files'][str(f.relative_to(a))]=sha(f.resolve())
        report['arm_toolchain']['note']='Existing project-local Debian GCC 11.3/QEMU 6.2 toolchain reused only as build/runtime assets; no Gorilla qualification inherited. Physical ARM not tested.'
    report['package_sources']={str(p.relative_to(ROOT)):sha(p) for d in ['include','src','tests','tools','vendor','patches','docs'] for p in (ROOT/d).rglob('*') if p.is_file() and '__pycache__' not in str(p)}
    report['package_sources']['CMakeLists.txt']=sha(ROOT/'CMakeLists.txt')
    (ROOT/'reports/BUILD_LOCK.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS build/runtime/source closure recorded:',len(report['profiles']),'profiles')
if __name__=='__main__':main()
