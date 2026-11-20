#!/bin/sh
# Recompute the representative real M4 report, without originals, builds, or network.
set -eu
if [ "$#" -ne 2 ]; then
    echo 'usage: sh tools/probe_offline_m4_real_profile.sh TSBENCH_PREFIX SEALED_RUN_DIRECTORY' >&2
    exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python_prefix=$(CDPATH= cd -- "$1" && pwd -P)
run=$(CDPATH= cd -- "$2" && pwd -P)
run_id=${run##*/}
case "$run_id" in *[!0-9a-f]*|'') exit 2 ;; esac
[ "${#run_id}" -eq 32 ] || exit 2
set -- /usr/bin/bwrap --unshare-net --unshare-pid --unshare-ipc --die-with-parent --clearenv --cap-drop ALL
for name in libc.so.6 libm.so.6 libdl.so.2 libutil.so.1 libpthread.so.0 libstdc++.so.6 libgcc_s.so.1; do
    path="/lib/x86_64-linux-gnu/$name"
    set -- "$@" --ro-bind "$path" "$path"
done
exec "$@" --ro-bind /lib64/ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2 \
    --ro-bind "$project/src" /control/src --ro-bind "$python_prefix" /toolchains/python \
    --ro-bind "$run" "/sealed/$run_id" --setenv PYTHONPATH /control/src --chdir /control \
    /toolchains/python/bin/python -B -c '
from pathlib import Path
import sys
from tsbench.application.m4_real_profile import recompute
from tsbench.assets import canonical_bytes
run = Path(sys.argv[1])
output = canonical_bytes(recompute(run)) + b"\n"
assert output == (run / "report.json").read_bytes()
sys.stdout.buffer.write(output)
' "/sealed/$run_id"
