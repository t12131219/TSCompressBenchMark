#!/bin/sh
# Prepare the declared toolchains first. The only writable host mount is OUT.
set -eu
mode=integrated
if [ "${1-}" = --release-builds-only ]; then
    mode=release
    shift
elif [ "${1-}" = --pluggability-only ]; then
    mode=pluggability
    shift
elif [ "${1-}" = --with-huff0-portable ]; then
    mode=integrated_with_huff0_portable
    shift
fi
if [ "$#" -ne 3 ]; then
    echo 'usage: tools/probe_offline_m0.sh [--release-builds-only|--pluggability-only|--with-huff0-portable] PYTHON_PREFIX RUST_TOOLCHAIN EMPTY_OUTPUT_DIR' >&2
    exit 2
fi
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python_prefix=$(CDPATH= cd -- "$1" && pwd -P)
rust_toolchain=$(CDPATH= cd -- "$2" && pwd -P)
out=$(CDPATH= cd -- "$3" && pwd -P)
if [ -n "$(ls -A -- "$out")" ]; then
    echo 'audit output directory must initially be empty' >&2
    exit 2
fi
exec bwrap --unshare-all --die-with-parent \
    --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
    --proc /proc --dev /dev --tmpfs /tmp \
    --ro-bind "$python_prefix" /toolchains/python --ro-bind "$rust_toolchain" /toolchains/rust \
    --symlink /usr/bin/gcc /toolchains/c-alias/bin/cc \
    --symlink /usr/bin/g++ /toolchains/c-alias/bin/c++ \
    --ro-bind "$project" /relocated-benchmark --bind "$out" /out --chdir /relocated-benchmark \
    --clearenv --setenv HOME /tmp --setenv PATH /toolchains/c-alias/bin:/toolchains/rust/bin:/usr/bin:/bin \
    --setenv PYTHONDONTWRITEBYTECODE 1 /bin/sh -ec '
        readlink /proc/self/ns/net > /out/network-namespace.txt
        runtime=/toolchains/python/bin/python
        "$runtime" -B -c '"'"'import json,sys; assert sys.version_info >= (3,11); print(json.dumps({"version":sys.version,"executable":sys.executable,"prefix":sys.prefix}))'"'"' > /out/python-runtime.json
        if [ "$1" = release ]; then
            exec "$runtime" -B /relocated-benchmark/tools/probe_release_builds.py --out /out/release-builds --jobs 6
        fi
        if [ "$1" = pluggability ]; then
            exec "$runtime" -I -B /relocated-benchmark/tests/isolation/plugin_authoring.py --out /out/pluggability
        fi
        "$runtime" -B /relocated-benchmark/bmk plan --out /out/scope-plan.json
        "$runtime" -B /relocated-benchmark/bmk native-contract-plan --out /out/native-contract-plan.json
        "$runtime" -B /relocated-benchmark/bmk native-admission-plan --out /out/native-admission-plan.json
        "$runtime" -B /relocated-benchmark/bmk corpus-profile > /out/corpus-profile.json
        PYTHONPATH=/relocated-benchmark/src "$runtime" -B -m unittest discover -s tests -v > /out/python.log 2>&1
        cmake -S /relocated-benchmark -B /out/abi-build -DCMAKE_BUILD_TYPE=Release -DTSBENCH_CORAD_DIAGNOSTIC=ON \
            -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DPython3_EXECUTABLE="$runtime" > /out/abi.log 2>&1
        cmake --build /out/abi-build --parallel 4 >> /out/abi.log 2>&1
        mode=$1
        set -- --build-dir /out/abi-build
        if [ "$mode" = integrated_with_huff0_portable ]; then
            cmake -S /relocated-benchmark -B /out/huff0-portable -DCMAKE_BUILD_TYPE=Release \
                -DTSBENCH_PLUGINS=huff0-reference -DENTROPY_DYNAMIC_BMI2=OFF -DPython3_EXECUTABLE="$runtime" > /out/huff0-portable.log 2>&1
            cmake --build /out/huff0-portable --parallel 4 --target tsbench_huff0_control >> /out/huff0-portable.log 2>&1
            set -- "$@" --huff0-portable-build /out/huff0-portable
        fi
        "$runtime" -B /relocated-benchmark/bmk native-plan "$@" --out /out/native-plan.json
        "$runtime" -B /relocated-benchmark/bmk native-run "$@" \
            --plan /out/native-plan.json --results /out/native-runs > /out/native-report.json
    ' sh "$mode"
