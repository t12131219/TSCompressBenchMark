#!/bin/sh
# Thin convenience entrypoint. Supply an existing Linux single-config build
# directory under the project root; CMake owns how the artifacts are built.
set -eu
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ "${CONDA_DEFAULT_ENV:-}" != tsbench ]; then
    echo 'activate tsbench; usage: scripts/smoke.sh PROJECT_RELATIVE_BUILD_DIRECTORY [SUITE]' >&2
    exit 2
fi
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$root"
build=$1
python="$CONDA_PREFIX/bin/python"
locks=$(mktemp -d "$build/smoke-plan.XXXXXXXX")
"$python" -B "$root/bmk" lock-build --worker "$build/tsbench_cpu_worker" \
    --plugin "raw-store=$build/plugins/codecs/raw-store/libbmk_raw_store.so" \
    --plugin "zstd=$build/plugins/codecs/zstd/libbmk_zstd.so" \
    --plugin "alp-auto=$build/plugins/codecs/alp-auto/libbmk_alp_auto.so" --out "$locks/build.json"
"$python" -B "$root/bmk" smoke-plan --build-lock "$locks/build.json" --suite "${2:-dev_lossless_smoke_v1}" --out "$locks/plan.json"
exec "$python" -B "$root/bmk" smoke-run --plan "$locks/plan.json"
