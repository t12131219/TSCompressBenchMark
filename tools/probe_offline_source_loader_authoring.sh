#!/bin/bash
# Run a versioned source-loader lifecycle on a reduced relocated copy, then replay from sealed files only.
set -euo pipefail
replay_only=false
if [[ ${1:-} == --replay-only ]]; then
  replay_only=true
  shift
fi
if { "$replay_only" && [[ $# != 2 ]]; } || { ! "$replay_only" && [[ $# != 3 ]]; }; then
  echo 'usage: bash tools/probe_offline_source_loader_authoring.sh TSBENCH_PREFIX MATCHING_TV_BUILD EMPTY_OUTPUT_DIR' >&2
  echo '   or: bash tools/probe_offline_source_loader_authoring.sh --replay-only TSBENCH_PREFIX COMPLETED_OUTPUT_DIR' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
if "$replay_only"; then
  out=$(CDPATH= cd -- "$2" && pwd -P)
  test -f "$out/audit.json"
else
  build=$(CDPATH= cd -- "$2" && pwd -P)
  mkdir -p -- "$3"
  out=$(CDPATH= cd -- "$3" && pwd -P)
  test -z "$(ls -A -- "$out")"
fi
base=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr
      --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64
      --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache
      --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin
      --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /code/src --ro-bind "$project/bmk" /code/bmk)
if ! "$replay_only"; then
  launch=("${base[@]}" --bind "$out" /evidence)
  for f in cmake tools schemas plugins catalog include third_party configs datasets tests; do
    launch+=(--ro-bind "$project/$f" "/code/$f")
  done
  for f in build-lock.json tsbench_tv_worker \
    plugins/codecs/alp-auto/{libbmk_alp_auto.so,libalp_native.so} \
    plugins/codecs/gorilla-derived/libbmk_gorilla_t_derived.so \
    plugins/codecs/sprintz-fire/{libbmk_sprintz_fire_u16_group.so,librepaired_codec.so}; do
    launch+=(--ro-bind "$build/$f" "/code/build/$f")
  done
  "${launch[@]}" --chdir /code /toolchain/bin/python -I -B tests/isolation/source_loader_authoring.py /evidence
fi
for tag in added upgraded remaining; do
  run_id=$("$prefix/bin/python" -I -B -c 'from pathlib import Path;import json,sys;print(json.loads(Path(sys.argv[1]).read_text())["runs"][sys.argv[2]]["run_id"])' "$out/audit.json" "$tag")
  [[ $run_id =~ ^[a-f0-9]{32}$ ]]
  run="$out/relocated project/results/$run_id"
  replay=("${base[@]}" --ro-bind "$run" /run --chdir /code)
  "${replay[@]}" /toolchain/bin/python -I -B /code/bmk tv-report /run > "$out/$tag-recomputed.json"
  original=$tag
  if [[ $tag == remaining ]]; then original=after-removal; fi
  cmp "$out/logs/run-$original.stdout" "$out/$tag-recomputed.json"
  "$prefix/bin/python" -I -B -c '
from hashlib import file_digest
import json, sys
from pathlib import Path
p, audit, recomputed = map(Path, sys.argv[1:4])
with p.open("rb") as f:
    assert file_digest(f,"sha256").hexdigest() == json.loads(audit.read_text())["runs"][sys.argv[4]]["report_sha256"]
assert json.loads(p.read_text()) == json.loads(recomputed.read_text())
' "$run/report.json" "$out/audit.json" "$out/$tag-recomputed.json" "$tag"
  "${replay[@]}" /toolchain/bin/python -I -B /code/bmk tv-restore-audit /run > "$out/$tag-restore.json"
done
