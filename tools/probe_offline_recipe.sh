#!/bin/bash
# Fresh selected build, one new recipe-bound run, detached replay.
set -euo pipefail
if [[ $# != 2 ]]; then
  echo 'usage: tools/probe_offline_recipe.sh TSBENCH_PREFIX EMPTY_OUTPUT_DIR' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
mkdir -p -- "$2"
out=$(CDPATH= cd -- "$2" && pwd -P)
test -z "$(ls -A -- "$out")"
mkdir -p "$out/runs" "$out/build"
base=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr
      --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64
      --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache
      --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin
      --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /code/src --ro-bind "$project/bmk" /code/bmk)
launch=("${base[@]}" --bind "$out/build" /code/build
    --bind "$out" /code/evidence --bind "$out/runs" /code/results)
for f in CMakeLists.txt cmake tools schemas plugins catalog include native tests third_party configs datasets assets environment; do
  launch+=(--ro-bind "$project/$f" "/code/$f")
done
"${launch[@]}" --chdir /code /bin/bash --noprofile --norc -euc '
  py=/toolchain/bin/python
  test ! -e /code/.git && test -z "$(ls -A results)"
  readlink /proc/self/ns/net > /code/evidence/net-namespace.txt
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DPython3_EXECUTABLE="$py" \
    "-DTSBENCH_PLUGINS=gorilla-t-derived;alp-auto;sprintz-fire-u16-group" > /code/evidence/configure.log
  cmake --build build --parallel 4 > /code/evidence/build.log 2>&1
  "$py" -I -B bmk lock-build --worker build/tsbench_tv_worker \
    --plugin gorilla-t-derived=build/plugins/codecs/gorilla-derived/libbmk_gorilla_t_derived.so \
    --plugin alp-auto=build/plugins/codecs/alp-auto/libbmk_alp_auto.so \
    --plugin sprintz-fire-u16-group=build/plugins/codecs/sprintz-fire/libbmk_sprintz_fire_u16_group.so \
    --out build/build-lock.json > /code/evidence/build-summary.json
  recipe=configs/recipes/tv-cross-format-v2.json
  PYTHONPATH=src "$py" -B -m unittest tests.contracts.test_recipe -v > /code/evidence/tests.log 2>&1
  "$py" -I -B bmk recipe-plan --recipe "$recipe" --build-lock build/build-lock.json \
    --out evidence/recipe-plan.json > /code/evidence/plan-summary.json
  "$py" -I -B bmk tv-run --plan evidence/recipe-plan.json > /code/evidence/report.json
  run=(results/*/)
  [[ ${#run[@]} -eq 1 ]]
  "$py" -I -B tests/integration/tv_cross_format.py /code "${run[0]}" build/build-lock.json /code/evidence/recipe-plan.json \
    > /code/evidence/controls.json
'
runs=("$out"/runs/*)
test "${#runs[@]}" -eq 1 && test -f "${runs[0]}/completion.json"
replay=("${base[@]}" --ro-bind "${runs[0]}" /run --chdir /code)
"${replay[@]}" /toolchain/bin/python -I -B /code/bmk tv-report /run > "$out/recomputed.json"
cmp "$out/report.json" "$out/recomputed.json"
"${replay[@]}" /toolchain/bin/python -I -B /code/bmk tv-restore-audit /run > "$out/restore.json"
