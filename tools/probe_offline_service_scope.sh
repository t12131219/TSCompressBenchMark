#!/bin/bash
# Compile M0's service definition with no adjacent project, build or results mount.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo 'usage: bash tools/probe_offline_service_scope.sh TSBENCH_PREFIX EMPTY_OUTPUT_DIR' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
mkdir -p -- "$2"
out=$(CDPATH= cd -- "$2" && pwd -P)
test -z "$(ls -A -- "$out")"
vm=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr
    --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64
    --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin)
for entry in bmk src schemas configs catalog datasets third_party plugins cmake tools include native assets CMakeLists.txt; do
  vm+=(--ro-bind "$project/$entry" "/relocated/$entry")
done
vm+=(--ro-bind "$project/tests/contracts/test_service_scope.py" /relocated/tests/contracts/test_service_scope.py
     --ro-bind "$prefix" /toolchain --bind "$out" /evidence --chdir /relocated)
"${vm[@]}" /bin/bash --noprofile --norc -euc '
  readlink /proc/self/ns/net > /evidence/net-namespace.txt
  test ! -d /relocated/build && test ! -d /relocated/results && test ! -d /home/fzg
  py=/toolchain/bin/python
  suite=first_batch_service_v4
  "$py" -I -B bmk plan --config "configs/suites/$suite/request.toml" --out /evidence/plan.json > /evidence/cli-summary.json
  "$py" -I -B bmk service-plan-verify --plan /evidence/plan.json > /evidence/verification.json
  PYTHONPATH=src "$py" -B -c '\''from pathlib import Path; from tsbench.api import plan, PlanRequest; from tsbench.assets import load_json, require; root=Path.cwd(); require(plan(root,PlanRequest("first_batch_service_v4")).document==load_json(Path("/evidence/plan.json")), "CLI/API parity mismatch"); print("CLI/API parity: PASS")'\'' > /evidence/api-parity.txt
  reject() {
    name=$1; shift
    set +e
    "$py" -I -B bmk "$@" > "/evidence/$name.json" 2> "/evidence/$name.stderr"
    code=$?
    set -e
    test "$code" -eq 2
  }
  reject worker-budget plan --suite "$suite" --max-workers 5
  reject unknown-option plan --suite "$suite" --selections 9
  reject bad-suite plan --suite "../outside"
  PYTHONPATH=src "$py" -B -m unittest discover -s tests/contracts -p test_service_scope.py -v > /evidence/tests.log 2>&1
'
