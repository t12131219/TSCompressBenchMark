"""Native build recipes for frozen codec source assets (C/RW ABI version 1).

These are codec compilation recipes only; no legacy Python control plane is used.
"""
from __future__ import annotations
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMANDS: list[list[str]] = []

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _run(command: list[str]) -> str:
    COMMANDS.append(command)
    done = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=900)
    if done.returncode:
        raise RuntimeError(f"command failed ({done.returncode}): {shlex.join(command)}\n{done.stdout}{done.stderr}")
    return done.stdout + done.stderr

def _lz4_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "lz4_frame"
    vendor = adapter / "vendor" / "lz4" / "lib"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_lz4_frame.c"),
        str(vendor / "lz4.c"),
        str(vendor / "lz4frame.c"),
        str(vendor / "lz4hc.c"),
        str(vendor / "xxhash.c"),
        "-o",
        str(output),
    ]


def _entropy_command(output: Path, profile: str, algorithm: str) -> list[str]:
    vendor = PROJECT_ROOT / "adapters/entropy_fse/vendor/lib"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-fno-common",
        f"-DTSCB_HUFF0={int(algorithm == 'huff0')}",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(vendor),
        str(PROJECT_ROOT / "adapters/entropy_fse/native/tscb_entropy.c"),
        *(
            str(vendor / name)
            for name in (
                "fse_compress.c",
                "fse_decompress.c",
                "huf_compress.c",
                "huf_decompress.c",
                "entropy_common.c",
                "hist.c",
            )
        ),
        "-o",
        str(output),
    ]


SPRINTZ_FAMILY = {
    'sprintz-delta': (0, 0), 'sprintz-fire': (1, 0),
    'sprintz-delta-huffman': (0, 1), 'sprintz-fire-huffman': (1, 1),
}


def _sprintz_family_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / 'adapters/sprintz_family'
    lock = json.loads((adapter / 'FROZEN_SOURCES.json').read_text())
    for record in lock['files']:
        if _sha256(PROJECT_ROOT / record['path']) != record['sha256']:
            raise RuntimeError(f'frozen Sprintz source changed: {record["path"]}')
    vendor = adapter / 'vendor/sprintz_family'
    # Baseline API/binding is deliberately compiled without native ISA flags.
    flags = ['-fPIC', '-fvisibility=hidden', '-Wall', '-Wextra', '-Wno-ignored-attributes',
             '-march=x86-64', '-fno-fast-math', '-ffp-contract=off']
    if profile == 'release':
        flags += ['-O3', '-DNDEBUG']
    elif profile == 'sanitizer':
        flags += ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-sanitize-recover=all']
    else:
        raise ValueError(f'unknown build profile: {profile}')
    isa = ['-mavx2', '-mbmi', '-mbmi2', '-mlzcnt', '-mpopcnt', '-fno-strict-aliasing']
    includes = [str(vendor / p) for p in ('include','src','tools','vendor/core','vendor/huff0/lib','vendor/huff0/lib/common','vendor/huff0/lib/compress')]
    inc = [v for path in includes for v in ('-I', path)]
    core = ['sprintz.cpp','format.cpp','sprintz_delta.cpp','sprintz_delta_rle.cpp',
            'sprintz_delta_lowdim.cpp','sprintz_xff.cpp','sprintz_xff_rle.cpp',
            'sprintz_xff_lowdim.cpp','delta.cpp','predict.cpp','univariate_8b.cpp']
    huff = ['common/entropy_common.c','common/fse_decompress.c','common/error_private.c',
            'compress/huf_compress.c','compress/fse_compress.c','compress/hist.c','decompress/huf_decompress.c']
    units = [(vendor / 'vendor/core' / p, True) for p in core]
    units += [(vendor / 'src/native_dispatch.cpp', True), (vendor / 'src/api.cpp', False)]
    units += [(vendor / 'vendor/huff0/lib' / p, False) for p in huff]
    objects = []
    unitdir = output.parent / 'sprintz-objects'; unitdir.mkdir()
    for i, (source, native) in enumerate(units):
        obj = unitdir / f'{i:02d}_{source.stem}.o'
        cxx = source.suffix == '.cpp'
        _run([os.environ.get('CXX' if cxx else 'CC','c++' if cxx else 'cc'),
              '-std=c++17' if cxx else '-std=c11', *flags, *(isa if native else []), *inc,
              '-MD', '-MF', str(obj.with_suffix('.o.d')), '-c', str(source), '-o', str(obj)])
        objects.append(str(obj))
    predictor, huffman = SPRINTZ_FAMILY[algorithm]
    return [os.environ.get('CXX', 'c++'), '-std=c++17', *[f for f in flags if f != '-fvisibility=hidden'], '-shared', '-Wl,-z,defs', '-Wl,-Bsymbolic-functions',
            f'-DTSCB_SPRINTZ_PREDICTOR={predictor}', f'-DTSCB_SPRINTZ_HUFFMAN={huffman}',
            f'-DTSCB_SPRINTZ_KEY="{algorithm}"',
            '-I', str(PROJECT_ROOT / 'native/include'), *inc,
            str(adapter / 'native/tscb_sprintz_family.cc'), *objects, '-o', str(output)]


def _zstd_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "zstd_frame"
    vendor = adapter / "vendor" / "zstd" / "lib"
    flags = [
        "-std=c11",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-DXXH_NAMESPACE=ZSTD_",
        "-DDYNAMIC_BMI2=0",
        "-DZSTD_LEGACY_SUPPORT=0",
        "-DZSTD_DISABLE_ASM",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_files = [
        *(vendor / "common").glob("*.c"),
        *(vendor / "compress").glob("*.c"),
        *(vendor / "decompress").glob("*.c"),
    ]
    source_files = sorted(source_files)
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_zstd_frame.c"),
        *(str(path) for path in source_files),
        "-o",
        str(output),
    ]


def _snappy_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "snappy_raw"
    vendor = adapter / "vendor" / "snappy"
    flags = [
        "-std=c++17",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DHAVE_CONFIG_H=0",
        "-DSNAPPY_HAVE_SSSE3=0",
        "-DSNAPPY_HAVE_NEON=0",
        "-DSNAPPY_HAVE_BMI2=0",
        "-DSNAPPY_HAVE_X86_CRC32=0",
        "-DSNAPPY_HAVE_NEON_CRC32=0",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_snappy_raw.cc"),
        str(vendor / "snappy-sinksource.cc"),
        str(vendor / "snappy-stubs-internal.cc"),
        str(vendor / "snappy.cc"),
        "-o",
        str(output),
    ]


def _lzsse2_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "lzsse2_raw"
    vendor = adapter / "vendor" / "lzsse" / "lzsse2"
    patch = adapter / "patches/0001-allocation-unaligned-pointer-safety.patch"
    patched = output.parent / "lzsse2.cpp"
    _run(["patch", "--batch", "--output", str(patched), str(vendor / "lzsse2.cpp"), str(patch)])
    flags = [
        "-std=c++17",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-unknown-pragmas",
        "-Wno-sign-compare",
        "-msse4.1",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-Wl,-Bsymbolic-functions",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_lzsse2_raw.cc"),
        str(patched),
        "-o",
        str(output),
    ]


def _lzsse8_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "lzsse8_raw"
    vendor = adapter / "vendor" / "lzsse" / "lzsse8"
    patch = adapter / "patches/0001-allocation-unaligned-pointer-safety.patch"
    patched = output.parent / "lzsse8.cpp"
    _run(["patch", "--batch", "--output", str(patched), str(vendor / "lzsse8.cpp"), str(patch)])
    flags = [
        "-std=c++17",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-unknown-pragmas",
        "-Wno-sign-compare",
        "-msse4.1",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-Wl,-Bsymbolic-functions",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_lzsse8_raw.cc"),
        str(patched),
        "-o",
        str(output),
    ]


def _brotli_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "brotli_stream"
    vendor = adapter / "vendor" / "brotli"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_files = sorted(
        [
            *(vendor / "common").glob("*.c"),
            *(vendor / "dec").glob("*.c"),
            *(vendor / "enc").glob("*.c"),
        ]
    )
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_brotli_stream.c"),
        *(str(path) for path in source_files),
        "-lm",
        "-o",
        str(output),
    ]


def _deflate_zlib_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "deflate_zlib"
    vendor = adapter / "vendor" / "zlib"
    flags = [
        "-std=c11",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DZ_HAVE_UNISTD_H",
        "-Wl,-Bsymbolic-functions",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_names = (
        "adler32.c",
        "compress.c",
        "crc32.c",
        "deflate.c",
        "gzclose.c",
        "gzlib.c",
        "gzread.c",
        "gzwrite.c",
        "infback.c",
        "inffast.c",
        "inflate.c",
        "inftrees.c",
        "trees.c",
        "uncompr.c",
        "zutil.c",
    )
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_deflate_zlib.c"),
        *(str(vendor / name) for name in source_names),
        "-o",
        str(output),
    ]


def _bzip2_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "bzip2_stream"
    vendor = adapter / "vendor" / "bzip2"
    flags = [
        "-std=c11",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-implicit-fallthrough",
        "-Wno-unused-but-set-variable",
        "-Wno-unused-parameter",
        "-D_POSIX_C_SOURCE=200809L",
        "-Wl,-Bsymbolic-functions",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_names = (
        "blocksort.c",
        "huffman.c",
        "crctable.c",
        "randtable.c",
        "compress.c",
        "decompress.c",
        "bzlib.c",
    )
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_bzip2_stream.c"),
        *(str(vendor / name) for name in source_names),
        "-o",
        str(output),
    ]


def _xz_command(output: Path, profile: str) -> tuple[list[str], dict[str, Any], str]:
    adapter = PROJECT_ROOT / "adapters/xz_stream"
    vendor = adapter / "vendor/xz"
    dependency_build = output.parent / "vendor-build"
    flags = "-DLZMA_LZ_DECODER_CONFIG=1"
    if profile == "sanitizer":
        flags += " -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined"
    configure = [
        "cmake",
        "-S",
        str(vendor),
        "-B",
        str(dependency_build),
        f"-DCMAKE_C_COMPILER={os.environ.get('CC', 'cc')}",
        f"-DCMAKE_BUILD_TYPE={('Release' if profile == 'release' else 'Debug')}",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        f"-DCMAKE_C_FLAGS={flags}",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DBUILD_TESTING=ON",
        "-DXZ_THREADS=no",
        "-DXZ_NLS=OFF",
        "-DXZ_CHECKS=crc32",
        "-DXZ_SANDBOX=no",
        "-DXZ_ENCODERS=lzma1;lzma2",
        "-DXZ_DECODERS=lzma1;lzma2",
        "-DXZ_MICROLZMA_ENCODER=OFF",
        "-DXZ_MICROLZMA_DECODER=OFF",
        "-DXZ_LZIP_DECODER=OFF",
        "-DXZ_CLMUL_CRC=OFF",
        "-DXZ_ARM64_CRC32=OFF",
        "-DXZ_LOONGARCH_CRC32=OFF",
        "-DXZ_ASM_I386=OFF",
        "-DHAVE__MM_MOVEMASK_EPI8=OFF",
        "-DXZ_TOOL_XZ=OFF",
        "-DXZ_TOOL_XZDEC=OFF",
        "-DXZ_TOOL_LZMADEC=OFF",
        "-DXZ_TOOL_LZMAINFO=OFF",
        "-DXZ_TOOL_SCRIPTS=OFF",
        "-DXZ_DOC=OFF",
    ]
    build = ["cmake", "--build", str(dependency_build), "--parallel", "2"]
    log = _run(configure) + _run(build)
    dependency_commands = json.loads((dependency_build / "compile_commands.json").read_text())
    command = [
        os.environ.get("CC", "cc"),
        "-std=c11",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        *(
            ["-O3", "-DNDEBUG"]
            if profile == "release"
            else ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
        ),
        "-shared",
        "-Wl,-Bsymbolic-functions",
        "-Wl,--no-undefined",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(vendor / "src/liblzma/api"),
        str(adapter / "native/tscb_xz_stream.c"),
        str(dependency_build / "liblzma.a"),
        "-o",
        str(output),
    ]
    return (
        command,
        {
            "dependency_configure": configure,
            "dependency_build": build,
            "dependency_compile_commands": dependency_commands,
            "dependency_archive_sha256": _sha256(dependency_build / "liblzma.a"),
        },
        log,
    )


def _lzss_dipperstein_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters/lzss_dipperstein"
    vendor = adapter / "vendor/lzss"
    patch = adapter / "patches/0001-binary-tree-sentinel-bounds.patch"
    patched_tree = output.parent / "tree.c"
    _run(["patch", "--batch", "--output", str(patched_tree), str(vendor / "tree.c"), str(patch)])
    return [
        os.environ.get("CC", "cc"),
        "-std=c11",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        *(
            ["-O3", "-DNDEBUG"]
            if profile == "release"
            else ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
        ),
        "-shared",
        "-Wl,--no-undefined",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(vendor),
        "-I",
        str(vendor / "bitfile"),
        str(adapter / "native/tscb_lzss_dipperstein.c"),
        str(vendor / "lzss.c"),
        str(patched_tree),
        str(vendor / "bitfile/bitfile.c"),
        "-o",
        str(output),
    ]


def _lzss_command(output: Path, profile: str) -> tuple[list[str], dict[str, Any], str]:
    adapter = PROJECT_ROOT / "adapters/lzss_raw"
    flags = ["-std=c++17", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    sources = [
        adapter / "native/tscb_lzss_raw.cc",
        adapter / "native/lzss_raw_codec.cc",
    ]
    closure = [
        *sources,
        adapter / "native/lzss_raw_codec.h",
        PROJECT_ROOT / "native/include/tscb_adapter_v1.h",
        PROJECT_ROOT / "native/include/tscb_native_timing.h",
    ]
    command = [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-Wl,--no-undefined",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(adapter / "native"),
        *map(str, sources),
        "-o",
        str(output),
    ]
    license_path = adapter / "LICENSE"
    evidence = {
        "implementation": "CPP17_REGISTERED_EI10_EJ4_C32_PROFILE",
        "core_execution_language": "C++17",
        "source_reference_commit": "512b9163d8a936003c925e24f7f682eeaeda8307",
        "compiler_flags": flags,
        "compiled_source_closure": [
            {"path": str(path.relative_to(PROJECT_ROOT)), "sha256": _sha256(path)}
            for path in sorted(closure)
        ],
        "native_timing_boundary": {
            "encode": "C++ core encode, including dictionary initialization",
            "decode": "C++ core decode, including dictionary initialization",
            "excluded": "ABI validation, strict bitstream validation, Python marshaling",
        },
        "license": {
            "spdx": "MIT",
            "files": [
                {
                    "path": str(license_path.relative_to(PROJECT_ROOT)),
                    "sha256": _sha256(license_path),
                }
            ],
        },
        "sanitizer_coverage": "CPP_CORE_AND_ABI_ASAN_UBSAN_SYSTEM_RUNTIME_UNINSTRUMENTED"
        if profile == "sanitizer"
        else "NOT_APPLICABLE",
    }
    return command, evidence, ""


def _alp_command(output: Path, profile: str, algorithm: str) -> list[str]:
    """Consume the exact safe-v1 release API; never reapply the legacy patches."""
    adapter = PROJECT_ROOT / "adapters" / "alp"
    lock = json.loads((adapter / "FROZEN_SOURCES.json").read_text())
    for record in lock["files"]:
        path = PROJECT_ROOT / record["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise RuntimeError(f"frozen ALP safe-v1 source changed: {path}")
    package = adapter / "vendor" / "alp_safe_v1"
    flags = ["-std=c++17", "-fPIC", "-fno-fast-math", "-ffp-contract=off",
             "-fno-strict-aliasing"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined,float-cast-overflow"]
    else:
        raise ValueError(f"unknown ALP build profile: {profile}")
    return [os.environ.get("CXX", "clang++"), *flags, "-shared",
            f"-DTSCB_ALP_RD={int(algorithm == 'alp-rd')}",
            "-I", str(PROJECT_ROOT / "native/include"),
            "-I", str(package / "include"), "-I", str(package / "vendor/include"),
            str(adapter / "native/tscb_alp.cc"), str(package / "src/codec.cpp"),
            *(str(package / "vendor/src" / name) for name in (
                "falp.cpp", "fastlanes_ffor.cpp", "fastlanes_unffor.cpp",
                "fastlanes_generated_ffor.cpp", "fastlanes_generated_unffor.cpp")),
            "-Wl,-z,defs", "-Wl,-Bsymbolic-functions", "-o", str(output)]


def _serf_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "serf"
    vendor = adapter / "vendor" / "serf"
    target = output.parent / "serf"
    shutil.copytree(vendor, target, dirs_exist_ok=True)
    patches = (
        adapter / "patches" / "0001-defined-bit-operations.patch",
        adapter / "patches" / "0002-prefix-mask-bounds.patch",
        adapter / "patches" / "0003-input-bit-stream-guard.patch",
    )
    directory = str(target.relative_to(PROJECT_ROOT))
    for patch in patches:
        _run(["git", "apply", "--check", f"--directory={directory}", str(patch)])
        _run(["git", "apply", f"--directory={directory}", str(patch)])
    flags = [
        "-std=c++17",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-vla",
        "-Wno-parentheses",
        "-Wno-unused-parameter",
        "-Wno-reorder",
        "-Wno-sign-compare",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_names = (
        "compressor/serf_qt_compressor.cc",
        "compressor/serf_xor_compressor.cc",
        "compressor_32/serf_qt_compressor_32.cc",
        "compressor_32/serf_xor_compressor_32.cc",
        "decompressor/serf_qt_decompressor.cc",
        "decompressor/serf_xor_decompressor.cc",
        "decompressor_32/serf_qt_decompressor_32.cc",
        "decompressor_32/serf_xor_decompressor_32.cc",
        "utils/elias_gamma_codec.cc",
        "utils/input_bit_stream.cc",
        "utils/output_bit_stream.cc",
        "utils/post_office_solver.cc",
        "utils/post_office_solver_32.cc",
        "utils/serf_utils_32.cc",
        "utils/serf_utils_64.cc",
    )
    return [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-Wl,--no-undefined",
        f"-DTSCB_SERF_XOR={int(algorithm == 'serf-xor')}",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(target / "src"),
        str(adapter / "native/tscb_serf.cc"),
        *(str(target / "src" / name) for name in source_names),
        "-o",
        str(output),
    ]


def _zfp_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "zfp"
    vendor = adapter / "vendor" / "zfp"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_names = (
        "zfp.c",
        "bitstream.c",
        "encode1f.c",
        "encode1d.c",
        "encode1i.c",
        "encode1l.c",
        "decode1f.c",
        "decode1d.c",
        "decode1i.c",
        "decode1l.c",
        "encode2f.c",
        "encode2d.c",
        "encode2i.c",
        "encode2l.c",
        "decode2f.c",
        "decode2d.c",
        "decode2i.c",
        "decode2l.c",
        "encode3f.c",
        "encode3d.c",
        "encode3i.c",
        "encode3l.c",
        "decode3f.c",
        "decode3d.c",
        "decode3i.c",
        "decode3l.c",
        "encode4f.c",
        "encode4d.c",
        "encode4i.c",
        "encode4l.c",
        "decode4f.c",
        "decode4d.c",
        "decode4i.c",
        "decode4l.c",
    )
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-Wl,--no-undefined",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(vendor / "include"),
        "-I",
        str(vendor / "src"),
        str(adapter / "native/tscb_zfp.c"),
        *(str(vendor / "src" / name) for name in source_names),
        "-lm",
        "-o",
        str(output),
    ]


def _neats_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "neats"
    vendor = adapter / "vendor" / "neats"
    flags = [
        "-std=gnu++20",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Wno-comment",
        "-Wno-unknown-pragmas",
        "-fno-tree-vectorize",
        "-fno-tree-slp-vectorize",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-Wl,--no-undefined",
        f"-DTSCB_NEATS={int(algorithm == 'neats-lossless-i64')}",
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(vendor / "include"),
        "-I",
        str(vendor / "lib/sdsl-lite/include"),
        "-I",
        str(vendor / "lib/sux"),
        str(adapter / "native/tscb_neats.cc"),
        "-o",
        str(output),
    ]


def _rewrite_lossless_command(
    output: Path, profile: str, algorithm: str
) -> tuple[list[str], dict[str, Any]]:
    adapter = PROJECT_ROOT / "adapters/rewrite_lossless"
    lock = json.loads((adapter / "FROZEN_APIS.json").read_text())
    entry = lock["algorithms"][algorithm]
    for record in entry["files"]:
        path = PROJECT_ROOT / record["path"]
        if _sha256(path) != record["sha256"]:
            raise RuntimeError(f"frozen standalone API changed: {record['path']}")
    vendor = adapter / "vendor" / entry["package"]
    if algorithm in {'elf','elf-plus'}:
        # Frozen originals stay immutable. Only a build-local copy receives the
        # same encode path with its internal decode/memcmp self-test removed.
        target = output.parent / 'patched-source'
        for package in ('elf','elf-plus'):
            shutil.copytree(adapter / 'vendor' / package, target / 'vendor' / package)
        _run(['patch','--batch','-p1','-d',str(target),'-i',
              str(adapter / 'patches/direct_core_no_validation.patch')])
        vendor = target / 'vendor' / entry['package']
    command = [
        "c++",
        "-std=c++17",
        "-fPIC",
        "-fvisibility=hidden",
        "-shared",
        "-Wl,--no-undefined",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-fno-fast-math",
        "-ffp-contract=off",
        "-pthread",
        f"-DTSCB_REWRITE_KIND={entry['kind']}",
        f'-DTSCB_REWRITE_KEY="{algorithm}"',
        "-I",
        str(PROJECT_ROOT / "native/include"),
        "-I",
        str(vendor / "include"),
        str(adapter / "native/tscb_rewrite_lossless.cc"),
        *[str(vendor / p) for p in entry["translation_units"]],
        "-o",
        str(output),
    ]
    command[1:1] = (
        ["-O3", "-DNDEBUG"]
        if profile == "release"
        else ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    )
    return (
        command,
        {
            "frozen_api_lock_sha256": _sha256(adapter / "FROZEN_APIS.json"),
            "source_closure": entry["files"],
            "standalone_package": entry["package"],
        },
    )



CHIMP_FAMILY = {
    'chimp': (1, False), 'chimp32': (2, False),
    'chimp128': (3, False), 'chimpn': (3, True),
    'chimp128-no-index': (4, False), 'chimpn32': (5, True),
    'pmc-mr': (7, False), 'swing-filter': (8, False),
    'swing-filter-disjoint': (9, False),
    'swing-filter-disjoint-quantized': (10, False),
}


def _chimp_family_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / 'adapters/chimp_family'
    lock = json.loads((adapter / 'FROZEN_SOURCES.json').read_text())
    for record in lock['files']:
        if _sha256(PROJECT_ROOT / record['path']) != record['sha256']:
            raise RuntimeError(f'frozen Chimp family source changed: {record["path"]}')
    method, variable = CHIMP_FAMILY[algorithm]
    vendor = adapter / 'vendor/chimp_family'
    flags = ['-std=c++17', '-fPIC', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
             '-Wno-misleading-indentation', '-fno-fast-math', '-ffp-contract=off']
    if profile == 'release':
        flags += ['-O3', '-DNDEBUG']
    elif profile == 'sanitizer':
        flags += ['-O1', '-g', '-fno-omit-frame-pointer', '-fsanitize=address,undefined']
    else:
        raise ValueError(f'unknown build profile: {profile}')
    return [os.environ.get('CXX', 'c++'), *flags, '-shared', '-Wl,-z,defs', '-Wl,-Bsymbolic-functions',
            f'-DTSCB_CHIMP_METHOD={method}', f'-DTSCB_CHIMP_VARIABLE_HISTORY={int(variable)}',
            f'-DTSCB_CHIMP_KEY="{algorithm}"', '-I', str(PROJECT_ROOT / 'native/include'),
            '-I', str(vendor / 'include'), str(adapter / 'native/tscb_chimp_family.cc'),
            str(vendor / 'src/canonical/chimp_family.cpp'), '-o', str(output)]
