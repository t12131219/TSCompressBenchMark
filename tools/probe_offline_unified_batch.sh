#!/bin/bash
# One frozen plan, one run, one ledger. Empty build; reports and restore replay without source or build.
set -euo pipefail
if [[ $# -lt 3 || $# -gt 4 || ( $# -eq 4 && $4 != --ordered && $4 != --entropy && $4 != --sprintz && $4 != --titchy-access && $4 != --titchy-stream && $4 != --intmult && $4 != --gorilla-state && $4 != --lzbench-session && $4 != --lzbench-profiles && $4 != --alp-decode && $4 != --zfp-native && $4 != --pbepla-native && $4 != --corad-inference && $4 != --corad-training && $4 != --huff0-bmi2 ) ]]; then
  echo 'usage: tools/probe_offline_unified_batch.sh TSBENCH_PREFIX RUST_TOOLCHAIN EMPTY_OUTPUT_DIR [--ordered|--entropy|--sprintz|--titchy-access|--titchy-stream|--intmult|--gorilla-state|--lzbench-session|--lzbench-profiles|--alp-decode|--zfp-native|--pbepla-native|--corad-inference|--corad-training|--huff0-bmi2]' >&2
  exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
prefix=$(CDPATH= cd -- "$1" && pwd -P)
rust=$(CDPATH= cd -- "$2" && pwd -P)
mkdir -p -- "$3"
out=$(CDPATH= cd -- "$3" && pwd -P)
test -z "$(ls -A -- "$out")"
mkdir "$out/runs"
reuse=${TSBENCH_REUSE_BUILD_EVIDENCE:-}
if [[ -n $reuse ]]; then
  reuse=$(CDPATH= cd -- "$reuse" && pwd -P)
  test "$reuse" != "$out" && test -s "$reuse/build/build-lock.json" && test -s "$reuse/ctest.log" && test -s "$reuse/net-namespace.txt"
  printf '%s\n' "$reuse" > "$out/reused-build-evidence.txt"
  build_mount=(--ro-bind "$reuse/build" /relocated/build)
else
  mkdir "$out/build"
  build_mount=(--bind "$out/build" /relocated/build)
fi
mode=${4:-}
portable_mount=()
portable_mode=
if [[ $mode == --huff0-bmi2 ]]; then
  mode=--corad-training
  portable_mode=portable
  mkdir "$out/huff0-portable"
  portable_mount=(--bind "$out/huff0-portable" /relocated/huff0-portable)
fi
base=(/usr/bin/bwrap --unshare-net --die-with-parent --clearenv --ro-bind /usr /usr
      --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64
      --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache
      --proc /proc --dev /dev --tmpfs /tmp --setenv LC_ALL C --setenv HOME /tmp)
mounted=("${base[@]}")
for f in CMakeLists.txt cmake tools schemas src bmk plugins catalog include native tests third_party configs datasets assets environment; do
  mounted+=(--ro-bind "$project/$f" "/relocated/$f")
done
"${mounted[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$rust" /rust --bind "$out" /evidence \
  "${build_mount[@]}" "${portable_mount[@]}" --bind "$out/runs" /relocated/results --chdir /relocated \
  --setenv PATH /rust/bin:/usr/bin:/bin /bin/bash --noprofile --norc -euc '
    py=/toolchain/bin/python
    export PYTHONDONTWRITEBYTECODE=1
    export CARGO_NET_OFFLINE=true
    test -z "$(ls -A results)"
    if [[ $2 != reuse ]]; then test -z "$(ls -A build)"; fi
    readlink /proc/self/ns/net > /evidence/net-namespace.txt
    plugins="alp-auto;zstd;titchy-batch;zfp-reversible;xz-baseline;pcodec-source-auto;pcodec-c-native-auto;gorilla-tv"
    extra_targets=() extra_lock=() extra_plan=()
    suite=extended-v5
    if [[ $1 == --ordered || $1 == --entropy || $1 == --sprintz || $1 == --titchy-access || $1 == --titchy-stream || $1 == --intmult || $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v6
      plugins="$plugins;selfstar-batch"
      extra_targets+=(tsbench_selfstar_ordered_control)
      extra_lock+=(--plugin selfstar-batch=build/plugins/codecs/selfstar-batch/libbmk_selfstar_batch.so)
      extra_plan+=(--selfstar-direct-control build/plugins/codecs/selfstar-batch/tsbench_selfstar_ordered_control)
    fi
    if [[ $1 == --entropy || $1 == --sprintz || $1 == --titchy-access || $1 == --titchy-stream || $1 == --intmult || $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v7
      plugins="$plugins;huff0-reference"
      extra_targets+=(tsbench_huff0_control)
      extra_lock+=(--plugin huff0-reference=build/plugins/codecs/huff0-reference/libbmk_huff0_reference.so)
      extra_plan+=(--huff0-direct-control build/plugins/codecs/huff0-reference/tsbench_huff0_control)
    fi
    if [[ $1 == --sprintz || $1 == --titchy-access || $1 == --titchy-stream || $1 == --intmult || $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v8
      plugins="$plugins;sprintz-fire"
      extra_targets+=(tsbench_sprintz_control)
      extra_lock+=(--plugin sprintz-fire=build/plugins/codecs/sprintz-fire/libbmk_sprintz_fire.so)
      extra_plan+=(--sprintz-direct-control build/plugins/codecs/sprintz-fire/tsbench_sprintz_control)
    fi
    if [[ $1 == --titchy-access || $1 == --titchy-stream || $1 == --intmult || $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v9
      extra_targets+=(tsbench_titchy_access_control)
      extra_plan+=(--titchy-access-control build/plugins/codecs/titchy-batch/tsbench_titchy_access_control)
    fi
    if [[ $1 == --titchy-stream || $1 == --intmult || $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v10
      extra_targets+=(tsbench_titchy_stream_control)
      extra_plan+=(--titchy-stream-control build/plugins/codecs/titchy-batch/tsbench_titchy_stream_control)
    fi
    if [[ $1 == --intmult || $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then suite=extended-v11; fi
    if [[ $1 == --gorilla-state || $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v12
      extra_targets+=(tsbench_gorilla_sealed_work_control)
    fi
    if [[ $1 == --lzbench-session || $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v13
      extra_targets+=(tsbench_lzbench_session_control)
    fi
    if [[ $1 == --lzbench-profiles || $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v14
      extra_targets+=(tsbench_lzbench_feature_control tsbench_lzbench_xz_sync_control)
    fi
    if [[ $1 == --alp-decode || $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v15
      extra_targets+=(tsbench_alp_decode_control)
    fi
    if [[ $1 == --zfp-native || $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v16
      extra_targets+=(tsbench_zfp_native_control tsbench_zfp_sealed_omp_control)
    fi
    if [[ $1 == --pbepla-native || $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v17
      plugins="$plugins;pbepla-rr"
      extra_targets+=(tsbench_pbepla_native_control tsbench_pbepla_replay_control)
      extra_lock+=(--plugin pbepla-rr=build/plugins/codecs/pbepla-rr/libbmk_pbepla_rr.so)
    fi
    if [[ $1 == --corad-inference || $1 == --corad-training ]]; then
      suite=extended-v18
      plugins="$plugins;corad-frozen"
      extra_targets+=(tsbench_corad_inference_control)
      extra_lock+=(--plugin corad-frozen=build/plugins/codecs/corad-frozen/libbmk_corad_frozen.so)
    fi
    if [[ $1 == --corad-training ]]; then
      suite=extended-v19
      extra_targets+=(tsbench_corad_training_control)
    fi
    if [[ $2 != reuse ]]; then
    /usr/bin/cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      "-DTSBENCH_PLUGINS=$plugins" -DPython3_EXECUTABLE="$py" > /evidence/configure.log 2>&1
    /usr/bin/cmake --build build --parallel 6 > /evidence/build.log 2>&1
    /usr/bin/cmake --build build --parallel 6 --target tsbench_zstd_batch_control tsbench_alp_fenv_control \
      tsbench_titchy_batch_control tsbench_xz_batch_control tsbench_pcodec_batch_control \
      tsbench_pcodec_pages_control tsbench_gorilla_batch_control "${extra_targets[@]}" > /evidence/tools-build.log 2>&1
    /usr/bin/ctest --test-dir build --output-on-failure > /evidence/ctest.log
    fi
    if [[ $3 == portable ]]; then
      suite=extended-v20
      /usr/bin/cmake -S . -B huff0-portable -DCMAKE_BUILD_TYPE=Release \
        -DTSBENCH_PLUGINS=huff0-reference -DENTROPY_DYNAMIC_BMI2=OFF -DPython3_EXECUTABLE="$py" > /evidence/portable-configure.log 2>&1
      /usr/bin/cmake --build huff0-portable --parallel 4 --target tsbench_huff0_control > /evidence/portable-build.log 2>&1
      extra_plan+=(--huff0-portable-build huff0-portable)
    fi
    PYTHONPATH=src "$py" -B -m unittest discover -s tests -v > /evidence/python.log 2>&1
    P=build/plugins/codecs
    lock=build/build-lock.json
    plan=build/batch-plan.json
    if [[ $2 == reuse ]]; then lock=/evidence/build-lock.json; plan=/evidence/batch-plan.json; fi
    "$py" -I -B bmk lock-build --worker build/tsbench_cpu_worker --out "$lock" \
      --plugin alp-auto=$P/alp-auto/libbmk_alp_auto.so --plugin zstd=$P/zstd/libbmk_zstd.so \
      --plugin titchy-batch=$P/titchy-batch/libbmk_titchy_batch.so --plugin zfp-reversible=$P/zfp-reversible/libbmk_zfp_reversible.so \
      --plugin xz-baseline=$P/zstd/libbmk_xz_baseline.so --plugin pcodec-source-auto=$P/pcodec/libbmk_pcodec_source_auto.so \
      --plugin pcodec-c-native-auto=$P/pcodec/libbmk_pcodec_c_native_auto.so --plugin gorilla-tv=$P/gorilla-tv/libbmk_gorilla_tv.so "${extra_lock[@]}"
    if [[ $2 == reuse ]]; then cmp "$lock" build/build-lock.json; fi
    "$py" -I -B bmk batch-execution-plan --suite "$suite" --build-lock "$lock" --out "$plan" \
      --direct-control "$P/zstd/tsbench_zstd_batch_control" --alp-fenv-control "$P/alp-auto/tsbench_alp_fenv_control" \
      --titchy-direct-control "$P/titchy-batch/tsbench_titchy_batch_control" --xz-direct-control "$P/zstd/tsbench_xz_batch_control" \
      --pcodec-direct-control "$P/pcodec/tsbench_pcodec_batch_control" --pcodec-wrapped-driver "$P/pcodec/tsbench_pcodec_pages_control" \
      --gorilla-direct-control "$P/gorilla-tv/tsbench_gorilla_batch_control" "${extra_plan[@]}"
    if [[ $suite == extended-v20 ]]; then
      submission=/evidence/submission-plan.json
      predecessor=third_party/provenance/m0-native-qualification-audit-20261119-r2.json
      # The predecessor audit is mounted from the project evidence, not accepted or relabelled.
      "$py" -I -B bmk native-submission-plan --execution-plan "$plan" --predecessor-audit "$predecessor" --out "$submission"
      "$py" -I -B bmk batch-execution-run --plan "$submission" --results results > /evidence/submission-report.json
      "$py" -I -B -c '"'"'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["execution_report"], indent=2, ensure_ascii=False, allow_nan=False))'"'"' \
        /evidence/submission-report.json > /evidence/report.json
    else
      "$py" -I -B bmk batch-execution-run --plan "$plan" --results results > /evidence/report.json
    fi
    runs=(results/*)
    test "${#runs[@]}" -eq 1
    "$py" -I -B tests/isolation/unified_batch_controls.py "$PWD" "${runs[0]}" "$plan" > /evidence/controls.json
' bash "$mode" "${reuse:+reuse}" "$portable_mode"
runs=("$out"/runs/*)
test "${#runs[@]}" -eq 1 && test -f "${runs[0]}/seal.json"
replay=("${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src
        --ro-bind "$project/bmk" /control/bmk --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin)
"${replay[@]}" /toolchain/bin/python -I -B bmk batch-execution-report /run > "$out/recomputed.json"
cmp "$out/report.json" "$out/recomputed.json"
"${replay[@]}" /toolchain/bin/python -I -B bmk batch-execution-restore /run > "$out/restore.json"
if [[ $mode == --entropy || $mode == --sprintz || $mode == --titchy-access || $mode == --titchy-stream || $mode == --intmult || $mode == --gorilla-state || $mode == --lzbench-session || $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/huff0_reseal.py" /control/tests/isolation/huff0_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/huff0_reseal.py /run > "$out/huff0-reseal.json"
fi
if [[ $mode == --sprintz || $mode == --titchy-access || $mode == --titchy-stream || $mode == --intmult || $mode == --gorilla-state || $mode == --lzbench-session || $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/sprintz_reseal.py" /control/tests/isolation/sprintz_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/sprintz_reseal.py /run > "$out/sprintz-reseal.json"
fi
if [[ $mode == --titchy-access || $mode == --titchy-stream || $mode == --intmult || $mode == --gorilla-state || $mode == --lzbench-session || $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/titchy_reseal.py" /control/tests/isolation/titchy_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/titchy_reseal.py /run > "$out/titchy-reseal.json"
fi
if [[ $mode == --intmult || $mode == --gorilla-state || $mode == --lzbench-session || $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/intmult_reseal.py" /control/tests/isolation/intmult_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/intmult_reseal.py /run > "$out/intmult-reseal.json"
fi
if [[ $mode == --gorilla-state || $mode == --lzbench-session || $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/gorilla_state_reseal.py" /control/tests/isolation/gorilla_state_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/gorilla_state_reseal.py /run > "$out/gorilla-state-reseal.json"
fi
if [[ $mode == --lzbench-session || $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/lzbench_session_reseal.py" /control/tests/isolation/lzbench_session_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/lzbench_session_reseal.py /run > "$out/lzbench-session-reseal.json"
fi
if [[ $mode == --lzbench-profiles || $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/lzbench_profiles_reseal.py" /control/tests/isolation/lzbench_profiles_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/lzbench_profiles_reseal.py /run > "$out/lzbench-profiles-reseal.json"
fi
if [[ $mode == --alp-decode || $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/alp_decode_reseal.py" /control/tests/isolation/alp_decode_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/alp_decode_reseal.py /run > "$out/alp-decode-reseal.json"
fi
if [[ $mode == --zfp-native || $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/zfp_native_reseal.py" /control/tests/isolation/zfp_native_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/zfp_native_reseal.py /run > "$out/zfp-native-reseal.json"
fi
if [[ $mode == --pbepla-native || $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/pbepla_native_reseal.py" /control/tests/isolation/pbepla_native_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/pbepla_native_reseal.py /run > "$out/pbepla-native-reseal.json"
fi
if [[ $mode == --corad-inference || $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/corad_inference_reseal.py" /control/tests/isolation/corad_inference_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/corad_inference_reseal.py /run > "$out/corad-inference-reseal.json"
fi
if [[ $mode == --corad-training ]]; then
  "${base[@]}" --ro-bind "$prefix" /toolchain --ro-bind "$project/src" /control/src \
    --ro-bind "$project/tests/isolation/corad_training_reseal.py" /control/tests/isolation/corad_training_reseal.py \
    --ro-bind "${runs[0]}" /run --chdir /control --setenv PATH /usr/bin:/bin \
    /toolchain/bin/python -I -B /control/tests/isolation/corad_training_reseal.py /run > "$out/corad-training-reseal.json"
fi
