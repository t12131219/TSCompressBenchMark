#!/bin/sh
# Execute the independent restoration and its negative controls from a relocated sealed run.
set -eu
if [ "$#" -ne 3 ]; then
    echo 'usage: tools/probe_offline_m1_restore.sh TSBENCH_PREFIX RESULTS_ROOT RUN_ID' >&2
    exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python_prefix=$(CDPATH= cd -- "$1" && pwd -P)
run_id=$3
case "$run_id" in
    *[!0-9a-f]*|'') echo 'invalid run id' >&2; exit 2 ;;
esac
[ "${#run_id}" -eq 32 ] || { echo 'invalid run id length' >&2; exit 2; }
run=$(CDPATH= cd -- "$2/results/$run_id" && pwd -P)
set -- /usr/bin/bwrap --unshare-net --die-with-parent --clearenv
# Only these host libs are visible to the outer control Python and Bubblewrap.
# The inner decoder namespace does not see any of these mounts.
for name in libselinux.so.1 libcap.so.2 libpcre2-8.so.0 libc.so.6 libm.so.6 libdl.so.2 libutil.so.1 libpthread.so.0 libstdc++.so.6 libgcc_s.so.1; do
    path="/lib/x86_64-linux-gnu/$name"
    set -- "$@" --ro-bind "$path" "$path"
done
exec "$@" --ro-bind /lib64/ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2 \
    --ro-bind /usr/bin/bwrap /usr/bin/bwrap --proc /proc --tmpfs /tmp --dev /dev \
    --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/smoke_restore.py" /control/smoke_restore.py \
    --ro-bind "$python_prefix" /toolchains/python --setenv PYTHONPATH /control/src \
    --ro-bind "$run" "/input/results/$run_id" --chdir /control \
    /toolchains/python/bin/python -B /control/smoke_restore.py /input "$run_id"
