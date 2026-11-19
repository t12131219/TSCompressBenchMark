#!/bin/bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo 'usage: tools/probe_offline_gorilla_roles.sh TSBENCH_PREFIX EMPTY_OUTPUT_DIR' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
mkdir -p -- "$2"
out=$(CDPATH= cd -- "$2" && pwd -P)
if [[ -n "$(ls -A -- "$out")" ]]; then
  echo 'probe output directory must be empty' >&2
  exit 2
fi
base=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr 
      --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 
      --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache 
      --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin)
build=("${base[@]}")
for f in CMakeLists.txt cmake tools schemas src bmk plugins catalog include native tests third_party configs datasets assets environment; do
  build+=(--ro-bind "$project/$f" "/relocated/$f")
done
"${build[@]}" --ro-bind "$prefix" /toolchain --bind "$out" /out --chdir /relocated /bin/bash --noprofile --norc -euc '
  readlink /proc/self/ns/net > /out/net-namespace.txt
  test ! -e /relocated/build && test ! -e /relocated/results
  cmake -S /relocated -B /out/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DPython3_EXECUTABLE=/toolchain/bin/python "-DTSBENCH_PLUGINS=gorilla-tv;gorilla-t-derived;gorilla-v-derived" > /out/configure.log
  cmake --build /out/build --parallel 4 > /out/build.log 2>&1
  ctest --test-dir /out/build --output-on-failure > /out/ctest.log
  PYTHONPATH=src /toolchain/bin/python -B -m unittest discover -s tests -v > /out/python.log 2>&1
'
runs=("$out"/build/gorilla-role-control/*)
test "${#runs[@]}" -eq 1 && test -f "${runs[0]}/completion.json"
replay=("${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src 
        --ro-bind "$project/tests/native_worker_support.py" /control/tests/native_worker_support.py 
        --ro-bind "$project/tests/isolation/gorilla_roles.py" /control/tests/isolation/gorilla_roles.py 
        --ro-bind "${runs[0]}" /run --chdir /control)
"${replay[@]}" /toolchain/bin/python -I -B /control/tests/isolation/gorilla_roles.py --report /run > "$out/recomputed.json"
cmp "$out/recomputed.json" "${runs[0]}/report.json"
"${replay[@]}" /toolchain/bin/python -I -B /control/tests/isolation/gorilla_roles.py --restore /run > "$out/restore.json"
