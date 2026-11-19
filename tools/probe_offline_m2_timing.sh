#!/bin/sh
# Recompute exact derived bytes with only control code, its interpreter and one sealed run.
set -eu
if [ "$#" -ne 2 ]; then
    echo 'usage: tools/probe_offline_m2_timing.sh TSBENCH_PREFIX RUN_ID' >&2
    exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python_prefix=$(CDPATH= cd -- "$1" && pwd -P)
run_id=$2
case "$run_id" in *[!0-9a-f]*|'') exit 2 ;; esac
[ "${#run_id}" -eq 32 ] || exit 2
run=$(CDPATH= cd -- "$project/results/$run_id" && pwd -P)
set -- /usr/bin/bwrap --unshare-net --die-with-parent --clearenv
for name in libc.so.6 libm.so.6 libdl.so.2 libutil.so.1 libpthread.so.0 libstdc++.so.6 libgcc_s.so.1; do
    path="/lib/x86_64-linux-gnu/$name"
    set -- "$@" --ro-bind "$path" "$path"
done
exec "$@" --ro-bind /lib64/ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2 \
    --ro-bind "$project/src" /control/src --ro-bind "$python_prefix" /toolchains/python \
    --ro-bind "$run" "/input/results/$run_id" --setenv PYTHONPATH /control/src --chdir /control \
    /toolchains/python/bin/python -B -c '
from pathlib import Path
import sys
from tsbench.application.timing import read_report
from tsbench.assets import canonical_bytes
run, report = read_report(Path("/input"), sys.argv[1])
output = canonical_bytes(report) + b"\n"
assert output == (run / "derived/report.json").read_bytes()
sys.stdout.buffer.write(output)
' "$run_id"
