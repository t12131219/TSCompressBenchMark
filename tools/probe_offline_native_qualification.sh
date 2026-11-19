#!/bin/bash
# Re-audit one sealed candidate. This does not submit or modify a run.
set -euo pipefail
if [[ $# != 3 ]]; then
  echo 'usage: bash tools/probe_offline_native_qualification.sh TSBENCH_PREFIX SEALED_RUN EMPTY_OUTPUT_DIR' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
run=$(CDPATH= cd -- "$2" && pwd -P)
mkdir -p -- "$3"
out=$(CDPATH= cd -- "$3" && pwd -P)
test -z "$(ls -A -- "$out")"
replay=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr \
  --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache \
  --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp --setenv PATH /usr/bin:/bin \
  --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src --ro-bind "$project/bmk" /control/bmk \
  --ro-bind "$project/schemas/qualification.schema.json" /control/schemas/qualification.schema.json \
  --ro-bind "$run" /run --chdir /control)
"${replay[@]}" /bin/bash --noprofile --norc -euc '
    test ! -e /home/fzg && test ! -e datasets && test ! -e build && test ! -e /run/report.json
    readlink /proc/self/ns/net >&2
    exec /toolchain/bin/python -I -B bmk native-qualification-audit /run
  ' > "$out/qualification-audit.json" 2> "$out/replay.log"

# A source drift must be refused even when the immutable run and returned JSON would otherwise be valid.
validator=src/tsbench/planner/native_admission.py
{ cat "$project/$validator"; printf '\n# Negative test: validator drift.\n'; } > "$out/negative-validator.py"
if "${replay[@]}" --ro-bind "$out/negative-validator.py" "/control/$validator" \
    /toolchain/bin/python -I -B bmk native-qualification-audit /run \
    > "$out/stale-validator.stdout" 2> "$out/stale-validator.stderr"; then
  echo 'stale validator unexpectedly audited the sealed run' >&2
  exit 1
fi
test ! -s "$out/stale-validator.stdout"
grep -Fq "frozen validator differs: $validator" "$out/stale-validator.stderr"
