#!/bin/bash
# Freeze one service resolution; mount only the previous matching build files, not reports/runs.
set -euo pipefail
if [[ $# != 3 ]]; then
  echo 'usage: bash tools/probe_offline_service_recipes.sh TSBENCH_PREFIX MATCHING_TV_BUILD EMPTY_OUTPUT_DIR' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
build=$(CDPATH= cd -- "$2" && pwd -P)
mkdir -p -- "$3"
out=$(CDPATH= cd -- "$3" && pwd -P)
test -z "$(ls -A -- "$out")"
vm=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr
    --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64
    --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin)
for entry in bmk src schemas configs catalog datasets third_party plugins cmake tools include native assets tests CMakeLists.txt; do
  vm+=(--ro-bind "$project/$entry" "/relocated/$entry")
done
for file in build-lock.json tsbench_tv_worker \
  plugins/codecs/alp-auto/{libbmk_alp_auto.so,libalp_native.so} \
  plugins/codecs/gorilla-derived/libbmk_gorilla_t_derived.so \
  plugins/codecs/sprintz-fire/{libbmk_sprintz_fire_u16_group.so,librepaired_codec.so}; do
  vm+=(--ro-bind "$build/$file" "/relocated/build/$file")
done
vm+=(--ro-bind "$prefix" /toolchain --bind "$out" /relocated/evidence --chdir /relocated)
"${vm[@]}" /bin/bash --noprofile --norc -euc '
  test ! -e /home/fzg && test ! -e results
  readlink /proc/self/ns/net > evidence/net-namespace.txt
  py=/toolchain/bin/python
  bindings=configs/suites/first_batch_service_v4/recipe-bindings.json
  "$py" -I -B bmk service-recipe-plan --bindings "$bindings" --build-lock build/build-lock.json \
    --out evidence/service-recipe-plan.json > evidence/cli-summary.json
  "$py" -I -B bmk service-recipe-verify --plan evidence/service-recipe-plan.json > evidence/verification.json
  if "$py" -I -B bmk tv-run --plan evidence/service-recipe-plan.json > evidence/not-executable.stdout 2> evidence/not-executable.stderr; then
    exit 1
  fi
  grep -q "tv-run requires an executable TV plan" evidence/not-executable.stderr
  test ! -e results
  "$py" -I -B tests/integration/service_recipe_resolution.py /relocated "$bindings" build/build-lock.json \
    evidence/service-recipe-plan.json > evidence/controls.json
'

# The fixed-T comparison requires all its providers; exercise catalog disabling, not just a missing build mapping.
awk '/^\[plugins\."alp-auto"\]$/ { disable = 1 } /^enabled = true$/ && disable { print "enabled = false"; disable = 0; next } { print }' \
  "$project/catalog/plugins.toml" > "$out/disabled-plugins.toml"
"${vm[@]}" --ro-bind "$out/disabled-plugins.toml" /relocated/catalog/plugins.toml \
  /toolchain/bin/python -I -B tests/integration/service_recipe_resolution.py --disabled > "$out/disabled-controls.json"
