#!/bin/bash
# One stage execution. All logs/checks point to the same sealed run; no external sources.
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 || ( $# -eq 3 && $3 != --limbs && $3 != --ingress ) ]]; then
  echo 'usage: tools/probe_offline_tv_composition.sh TSBENCH_PREFIX EMPTY_OUTPUT_DIR [--limbs|--ingress]' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
mkdir -p -- "$2"
out=$(CDPATH= cd -- "$2" && pwd -P)
test -z "$(ls -A -- "$out")"
mkdir -p "$out/build" "$out/runs"
base=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr
      --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64
      --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache
      --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin)
build=("${base[@]}")
for f in CMakeLists.txt cmake tools schemas src bmk plugins catalog include native tests third_party configs datasets assets environment; do
  build+=(--ro-bind "$project/$f" "/relocated/$f")
done
"${build[@]}" --ro-bind "$prefix" /toolchain --bind "$out" /evidence --bind "$out/build" /relocated/build \
  --bind "$out/runs" /relocated/results --chdir /relocated /bin/bash --noprofile --norc -euc '
  py=/toolchain/bin/python
  test ! -e /relocated/.git
  test -z "$(ls -A build)" && test -z "$(ls -A results)"
  readlink /proc/self/ns/net > /evidence/net-namespace.txt
  common=(--plugin gorilla-t-derived=build/plugins/codecs/gorilla-derived/libbmk_gorilla_t_derived.so
          --plugin alp-auto=build/plugins/codecs/alp-auto/libbmk_alp_auto.so)
  if [[ $1 == --limbs || $1 == --ingress ]]; then
    plugins="gorilla-t-derived;alp-auto;sprintz-fire;sprintz-fire-u16-group"
    bindings=("${common[@]}" --plugin sprintz-fire-u16-group=build/plugins/codecs/sprintz-fire/libbmk_sprintz_fire_u16_group.so)
    suite=(--suite configs/suites/dev_tv_limb_comparison_v1/suite.json)
    integration=tv_limb_comparison.py
    if [[ $1 == --ingress ]]; then
      suite=(--suite configs/suites/dev_tv_cross_format_v2/suite.json)
      integration=tv_cross_format.py
      "$py" -I -B tools/generate_m3_ingress_fixtures.py --check
    fi
  else
    plugins="gorilla-tv;gorilla-t-derived;gorilla-v-derived;raw-timestamp;alp-auto"
    bindings=("${common[@]}" --plugin gorilla-tv=build/plugins/codecs/gorilla-tv/libbmk_gorilla_tv.so
              --plugin gorilla-v-derived=build/plugins/codecs/gorilla-derived/libbmk_gorilla_v_derived.so
              --plugin raw-timestamp=build/plugins/codecs/raw-timestamp/libbmk_raw_timestamp.so)
    suite=()
    integration=tv_composition.py
  fi
  cmake -S /relocated -B /relocated/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DPython3_EXECUTABLE="$py" "-DTSBENCH_PLUGINS=$plugins" > /evidence/configure.log
  cmake --build build --parallel 4 > /evidence/build.log 2>&1
  ctest --test-dir build --output-on-failure > /evidence/ctest.log
  PYTHONPATH=src "$py" -B -m unittest discover -s tests -v > /evidence/python.log 2>&1
  "$py" -I -B bmk lock-build --worker build/tsbench_tv_worker "${bindings[@]}" --out build/build-lock.json
  "$py" -I -B bmk tv-plan --build-lock build/build-lock.json "${suite[@]}" --out build/tv-plan.json
  "$py" -I -B bmk tv-run --plan build/tv-plan.json > /evidence/report.json
  runs=(results/*)
  [[ ${#runs[@]} -eq 1 ]]
  "$py" -I -B "tests/integration/$integration" /relocated "${runs[0]}" build/build-lock.json build/tv-plan.json > /evidence/controls.json
' bash "${3:-}"
runs=("$out"/runs/*)
test "${#runs[@]}" -eq 1 && test -f "${runs[0]}/completion.json"
replay=("${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src
        --ro-bind "$project/bmk" /control/bmk --ro-bind "${runs[0]}" /run --chdir /control)
"${replay[@]}" /toolchain/bin/python -I -B /control/bmk tv-report /run > "$out/recomputed.json"
cmp "$out/report.json" "$out/recomputed.json"
"${replay[@]}" /toolchain/bin/python -I -B /control/bmk tv-restore-audit /run > "$out/restore.json"
