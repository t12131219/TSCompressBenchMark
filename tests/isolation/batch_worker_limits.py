"""Exercise actual process ceilings through the same files-only worker launcher."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import digest, load_json
from tsbench.planner.linear_batch import batch_limits
from tsbench.supervisor.isolated_worker import invoke_isolated_worker

SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>
int main(int argc, char **argv) {
    struct rlimit as, fs, core;
    if (argc < 2 || getrlimit(RLIMIT_AS, &as) || getrlimit(RLIMIT_FSIZE, &fs) ||
        getrlimit(RLIMIT_CORE, &core) || as.rlim_cur != EXPECT_AS || as.rlim_max != as.rlim_cur ||
        fs.rlim_cur != EXPECT_FILE || fs.rlim_max != fs.rlim_cur || core.rlim_max != 0 ||
        access("/usr", F_OK) == 0 || access("/inputs/original", F_OK) == 0) return 12;
    if (strcmp(argv[1], "bounded-memory") == 0) {
        void *p = mmap(0, as.rlim_cur, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (p != MAP_FAILED || errno != ENOMEM) return 13;
        puts("ENOMEM");
        return 0;
    }
    if (strcmp(argv[1], "bounded-file") == 0) {
        char data[4096] = {0};
        int fd = open("/out/overflow", O_WRONLY | O_CREAT | O_EXCL, 0600);
        if (fd < 0) return 14;
        for (size_t done = 0; done < fs.rlim_cur;) {
            size_t n = fs.rlim_cur - done;
            if (n > sizeof data) n = sizeof data;
            if (write(fd, data, n) != (ssize_t)n) return 15;
            done += n;
        }
        if (write(fd, data, 1) != 1) return 15;
        return 16;
    }
    if (strcmp(argv[1], "bounded-wall") == 0) for (;;) pause();
    return 17;
}
'''


def main(run, method_name='zstd'):
    plan = load_json(run / 'plan.json')
    spec, limits = plan['decoder'], batch_limits(plan, {'method':method_name})
    method = plan['method'] if 'method' in plan else plan['methods'][method_name]
    with tempfile.TemporaryDirectory(prefix='tsbench-limit-control-') as tmp:
        directory = Path(tmp)
        exe, code = directory / 'control', directory / 'probe.c'
        code.write_text(SOURCE)
        subprocess.run(['/usr/bin/cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        f"-DEXPECT_AS={limits['address_space_bytes']}", f"-DEXPECT_FILE={limits['file_bytes']}",
                        str(code), '-o', str(exe)],
                       check=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        for name in spec['files']:
            if name != spec['worker']:
                dst = directory / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(run / 'recovery' / name, dst)
        target = directory / spec['worker']
        target.parent.mkdir(exist_ok=True)
        exe.rename(target)
        spec['files'][spec['worker']].update(bytes=target.stat().st_size, sha256=digest(target))
        result = {}
        for mode in ('bounded-memory', 'bounded-file', 'bounded-wall'):
            work = directory / mode
            work.mkdir()
            timeout = {**limits, 'wall_seconds': 1 if mode == 'bounded-wall' else limits['wall_seconds']}
            out, obs = invoke_isolated_worker(directory, spec, method, timeout, work, work, mode, {}, [], lambda:False)
            result[mode] = obs
            if mode == 'bounded-memory':
                assert obs['status'] == 'completed' and (work / f'{mode}.stdout').read_text() == 'ENOMEM\n', obs
            elif mode == 'bounded-file':
                assert obs['status'] == 'file_limit_signal' and (out / 'overflow').stat().st_size == limits['file_bytes'], obs
            else:
                assert obs['status'] == 'timeout', obs
        print(json.dumps({'schema': 'bmk.batch-launcher-limit-control/1', 'tested_limits': limits,
                          'operations': result}, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(strict=True), *sys.argv[2:])
