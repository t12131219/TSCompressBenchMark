#!/usr/bin/env python3
"""Build only new M4 driver executables; reuse the sealed native libraries and overlays."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.profiling import DRIVER, LIBS, OVERLAY
from tsbench.application.smoke import write_new
from tsbench.assets import digest, local_file, require

SOURCE = 'native/measurement/profile_driver.cpp'


def build(out, plain, profile):
    out = out.resolve()
    require(out.is_relative_to(ROOT) and not out.exists(), 'profile driver build requires a new project directory')
    out.mkdir(parents=True)
    native_dirs = {'plain': plain, 'profile': profile}
    arms = {}
    for arm, directory in native_dirs.items():
        side = out / arm
        side.mkdir()
        build_root = (ROOT / directory).resolve(strict=True)
        with_trace = arm == 'profile'
        targets = (*LIBS, 'libtsbench_trace.so') if with_trace else LIBS
        assets = [local_file(build_root, p) for p in targets]
        includes = ('include', 'native/tracing', f'{directory}/plugins/codecs/alp-auto/source/alp-native/include',
                    f'{directory}/plugins/codecs/zstd/source/lzbench-native/include')
        args = ['/usr/bin/c++', '-std=c++17', '-O3', '-DNDEBUG', '-Wall', '-Wextra', '-Werror',
                *(('-DTSBENCH_PROFILE_BUILD=1',) if with_trace else ()), *('-I' + i for i in includes), SOURCE,
                *(str(p.relative_to(ROOT)) for p in assets), '-Wl,-rpath,$ORIGIN', '-o', str((side / DRIVER).relative_to(ROOT))]
        subprocess.run(args, cwd=ROOT, check=True)
        links = subprocess.run(['/usr/bin/readelf', '-Wd', str(side / DRIVER)], cwd=ROOT, check=True,
                               text=True, capture_output=True).stdout
        require(all(p.name in links for p in assets) and ('libtsbench_trace.so' in links) == with_trace,
                'profile driver ELF runtime differs from arm')
        evidence = [local_file(build_root, p) for p in OVERLAY] if with_trace else []
        # Bind headers as well as driver source to reproduce this standalone build.
        headers = sorted({p for d in includes for p in (ROOT / d).rglob('*') if p.suffix in ('.h', '.hpp') and p.is_file()})
        refs = {p.relative_to(ROOT).as_posix(): digest(p) for p in [*assets, *evidence, *headers, side / DRIVER]}
        arms[arm] = {'argv': args, 'sources': refs, 'runtime': [p.relative_to(ROOT).as_posix() for p in assets],
                     'driver': (side / DRIVER).relative_to(ROOT).as_posix()}
    manifest = {'schema': 'bmk.m4-real-profile-driver-build/1', 'source': {SOURCE: digest(ROOT / SOURCE)},
                'compiler': {'path': '/usr/bin/c++', 'sha256': digest(Path('/usr/bin/c++'))}, 'arms': arms}
    write_new(out / 'build.json', manifest)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--plain', required=True)
    p.add_argument('--profile', required=True)
    a = p.parse_args()
    build(a.out, a.plain, a.profile)
