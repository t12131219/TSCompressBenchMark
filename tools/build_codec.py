from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {shlex.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def _lz4_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "lz4_frame"
    vendor = adapter / "vendor" / "lz4" / "lib"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        os.environ.get("CC", "cc"), *flags, "-shared", "-fno-common",
        f"-DTSCB_HUFF0={int(algorithm == 'huff0')}",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(vendor),
        str(PROJECT_ROOT / "adapters/entropy_fse/native/tscb_entropy.c"),
        *(str(vendor / name) for name in (
            "fse_compress.c", "fse_decompress.c", "huf_compress.c",
            "huf_decompress.c", "entropy_common.c", "hist.c",
        )), "-o", str(output),
    ]


def _sprintz_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters/sprintz"
    vendor = adapter / "vendor/sprintz"
    patch = adapter / "patches/0001-lowdim-byte-safety.patch"
    target = output.parent / "sprintz"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("sprintz_delta_lowdim.cpp", "sprintz_xff_lowdim.cpp", "bitpack.h"):
        shutil.copy2(vendor / name, target / name)
    directory = str(output.parent.relative_to(PROJECT_ROOT))
    _run(["git", "apply", "--check", f"--directory={directory}", str(patch)])
    _run(["git", "apply", f"--directory={directory}", str(patch)])
    flags = ["-std=c++17", "-fPIC", "-Wno-ignored-attributes", "-w",
             "-mavx2", "-mbmi2", "-mlzcnt"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"), *flags, "-shared", "-Wl,-Bsymbolic-functions",
        f"-DTSCB_SPRINTZ_FIRE={int(algorithm == 'sprintz-fire-u8')}",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(vendor),
        str(adapter / "native/tscb_sprintz8.cc"),
        str(adapter / "native/bounded_lowdim.cc"),
        str(target / "sprintz_delta_lowdim.cpp"),
        str(target / "sprintz_xff_lowdim.cpp"), "-o", str(output),
    ]


def _sprintz_full_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters/sprintz"
    vendor = adapter / "vendor/sprintz"
    patches = (
        adapter / "patches/0001-lowdim-byte-safety.patch",
        adapter / "patches/0002-generic-allocation-safety.patch",
    )
    target = output.parent / "sprintz"
    target.mkdir(parents=True, exist_ok=True)
    sources = (
        "sprintz.cpp",
        "sprintz_delta_lowdim.cpp",
        "sprintz_xff_lowdim.cpp",
        "sprintz_delta_rle.cpp",
        "sprintz_xff_rle.cpp",
        "format.cpp",
    )
    for name in (*sources, "bitpack.h"):
        shutil.copy2(vendor / name, target / name)
    directory = str(output.parent.relative_to(PROJECT_ROOT))
    for patch in patches:
        _run(["git", "apply", "--check", f"--directory={directory}", str(patch)])
        _run(["git", "apply", f"--directory={directory}", str(patch)])
    flags = [
        "-std=c++17", "-fPIC", "-Wno-ignored-attributes", "-w",
        "-mavx2", "-mbmi2", "-mlzcnt", "-fno-strict-aliasing",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
            "-fno-sanitize=alignment",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"), *flags, "-shared", "-Wl,-Bsymbolic-functions",
        f"-DTSCB_SPRINTZ_FIRE={int(algorithm == 'sprintz-fire')}",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(target), "-I", str(vendor),
        str(adapter / "native/tscb_sprintz.cc"),
        str(adapter / "native/bounded_sprintz.cc"),
        *(str(target / name) for name in sources),
        "-o", str(output),
    ]


def _sprintz_fire_huff0_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters/sprintz"
    vendor = adapter / "vendor/sprintz"
    entropy = PROJECT_ROOT / "adapters/entropy_fse/vendor/lib"
    patches = (
        adapter / "patches/0001-lowdim-byte-safety.patch",
        adapter / "patches/0002-generic-allocation-safety.patch",
        adapter / "patches/0003-fire-prediction-overflow.patch",
    )
    target = output.parent / "sprintz"
    target.mkdir(parents=True, exist_ok=True)
    sprintz_sources = (
        "sprintz.cpp",
        "sprintz_delta_lowdim.cpp",
        "sprintz_xff_lowdim.cpp",
        "sprintz_delta_rle.cpp",
        "sprintz_xff_rle.cpp",
        "format.cpp",
    )
    entropy_sources = (
        "fse_compress.c",
        "fse_decompress.c",
        "huf_compress.c",
        "huf_decompress.c",
        "entropy_common.c",
        "hist.c",
    )
    for name in (*sprintz_sources, "bitpack.h"):
        shutil.copy2(vendor / name, target / name)
    directory = str(output.parent.relative_to(PROJECT_ROOT))
    for patch in patches:
        _run(["git", "apply", "--check", f"--directory={directory}", str(patch)])
        _run(["git", "apply", f"--directory={directory}", str(patch)])
    flags = [
        "-std=c++17", "-fPIC", "-Wno-ignored-attributes", "-w",
        "-mavx2", "-mbmi2", "-mlzcnt", "-fno-strict-aliasing",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
            "-fno-sanitize=alignment",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"), *flags, "-shared", "-Wl,-Bsymbolic-functions",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(target),
        "-I", str(vendor), "-I", str(entropy),
        str(adapter / "native/tscb_sprintz_fire_huff0.cc"),
        str(adapter / "native/bounded_sprintz.cc"),
        *(str(target / name) for name in sprintz_sources),
        *(str(entropy / name) for name in entropy_sources),
        "-o", str(output),
    ]


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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
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
        "cmake", "-S", str(vendor), "-B", str(dependency_build),
        f"-DCMAKE_C_COMPILER={os.environ.get('CC', 'cc')}",
        f"-DCMAKE_BUILD_TYPE={'Release' if profile == 'release' else 'Debug'}",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        f"-DCMAKE_C_FLAGS={flags}", "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTING=ON",
        "-DXZ_THREADS=no", "-DXZ_NLS=OFF", "-DXZ_CHECKS=crc32", "-DXZ_SANDBOX=no",
        "-DXZ_ENCODERS=lzma1;lzma2", "-DXZ_DECODERS=lzma1;lzma2",
        "-DXZ_MICROLZMA_ENCODER=OFF", "-DXZ_MICROLZMA_DECODER=OFF", "-DXZ_LZIP_DECODER=OFF",
        "-DXZ_CLMUL_CRC=OFF", "-DXZ_ARM64_CRC32=OFF", "-DXZ_LOONGARCH_CRC32=OFF",
        "-DXZ_ASM_I386=OFF", "-DHAVE__MM_MOVEMASK_EPI8=OFF",
        "-DXZ_TOOL_XZ=OFF", "-DXZ_TOOL_XZDEC=OFF", "-DXZ_TOOL_LZMADEC=OFF",
        "-DXZ_TOOL_LZMAINFO=OFF", "-DXZ_TOOL_SCRIPTS=OFF", "-DXZ_DOC=OFF",
    ]
    build = ["cmake", "--build", str(dependency_build), "--parallel", "2"]
    log = _run(configure) + _run(build)
    dependency_commands = json.loads((dependency_build / "compile_commands.json").read_text())
    command = [
        os.environ.get("CC", "cc"), "-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror",
        *( ["-O3", "-DNDEBUG"] if profile == "release" else
           ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"] ),
        "-shared", "-Wl,-Bsymbolic-functions", "-Wl,--no-undefined",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(vendor / "src/liblzma/api"),
        str(adapter / "native/tscb_xz_stream.c"), str(dependency_build / "liblzma.a"),
        "-o", str(output),
    ]
    return command, {
        "dependency_configure": configure, "dependency_build": build,
        "dependency_compile_commands": dependency_commands,
        "dependency_archive_sha256": _sha256(dependency_build / "liblzma.a"),
    }, log


def _lzss_dipperstein_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters/lzss_dipperstein"
    vendor = adapter / "vendor/lzss"
    patch = adapter / "patches/0001-binary-tree-sentinel-bounds.patch"
    patched_tree = output.parent / "tree.c"
    _run(["patch", "--batch", "--output", str(patched_tree), str(vendor / "tree.c"), str(patch)])
    return [
        os.environ.get("CC", "cc"), "-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror",
        *(["-O3", "-DNDEBUG"] if profile == "release" else
          ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]),
        "-shared", "-Wl,--no-undefined", "-I", str(PROJECT_ROOT / "native/include"),
        "-I", str(vendor), "-I", str(vendor / "bitfile"),
        str(adapter / "native/tscb_lzss_dipperstein.c"),
        str(vendor / "lzss.c"), str(patched_tree),
        str(vendor / "bitfile/bitfile.c"),
        "-o", str(output),
    ]


def _lzss_command(output: Path, profile: str) -> tuple[list[str], dict[str, Any], str]:
    adapter = PROJECT_ROOT / "adapters/lzss_raw"
    vendor = adapter / "vendor/lzss/lzss"
    dependency = output.parent / "rust-build"
    dependency.mkdir(parents=True, exist_ok=True)
    flags = ["-C", "relocation-model=pic", "-C", "opt-level=3"]
    rust_environment: dict[str, str] = {}
    if profile == "sanitizer":
        flags = ["-C", "relocation-model=pic", "-C", "opt-level=1", "-g",
                 "-C", "debug-assertions=yes", "-Z", "sanitizer=address"]
        rust_environment = {"RUSTC_BOOTSTRAP": "1"}
    features = ["--cfg", 'feature="std"', "--cfg", 'feature="alloc"',
                "--cfg", 'feature="safe"']
    commands = [
        ["rustc", str(adapter / "vendor/void/src/lib.rs"), "--crate-name", "void",
         "--crate-type", "rlib", "--cfg", 'feature="std"', *flags,
         "-o", str(dependency / "libvoid.rlib")],
        ["rustc", str(vendor / "build.rs"), "-o", str(dependency / "generate")],
        [str(dependency / "generate")],
        ["rustc", str(vendor / "src/lib.rs"), "--edition=2021", "--crate-name", "lzss",
         "--crate-type", "rlib", *features, *flags,
         "--extern", f"void={dependency / 'libvoid.rlib'}", "-L", str(dependency),
         "-o", str(dependency / "liblzss.rlib")],
        ["rustc", str(adapter / "native/ffi.rs"), "--edition=2021",
         "--crate-name", "tscb_lzss", "--crate-type", "staticlib", *flags,
         "--extern", f"lzss={dependency / 'liblzss.rlib'}", "-L", str(dependency),
         "-o", str(dependency / "libtscb_lzss.a")],
    ]
    log = ""
    environment = {**os.environ, **rust_environment, "OUT_DIR": str(dependency)}
    for command in commands:
        completed = subprocess.run(command, cwd=vendor, env=environment, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log += completed.stdout
        if completed.returncode:
            raise RuntimeError(f"Rust build failed: {shlex.join(command)}\n{completed.stdout}")
    command = [
        os.environ.get("CXX", "c++"), "-std=c++17", "-fPIC", "-Wall", "-Wextra", "-Werror",
        *(["-O3", "-DNDEBUG"] if profile == "release" else
          ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]),
        "-shared", "-Wl,--exclude-libs,ALL", "-I", str(PROJECT_ROOT / "native/include"),
        str(adapter / "native/tscb_lzss_raw.cc"), str(dependency / "libtscb_lzss.a"),
        "-lpthread", "-ldl", "-lm", "-o", str(output),
    ]
    return command, {
        "dependency_commands": commands, "dependency_environment": rust_environment,
        "rustc": _run(["rustc", "--version"]),
        "dependency_archive_sha256": _sha256(dependency / "libtscb_lzss.a"),
        "sanitizer_coverage": "RUST_CODEC_AND_FFI_ASAN_CPP_ASAN_UBSAN_STD_UNINSTRUMENTED"
        if profile == "sanitizer" else "NOT_APPLICABLE",
    }, log


def _alp_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "alp"
    vendor = adapter / "vendor" / "alp"
    target = output.parent / "alp"
    shutil.copytree(vendor, target, dirs_exist_ok=True)
    patches = (
        adapter / "patches" / "0001-float-factor-array-bound.patch",
        adapter / "patches" / "0002-decoder-multiply-domain.patch",
        adapter / "patches" / "0003-encoded-integer-range.patch",
    )
    directory = str(output.parent.relative_to(PROJECT_ROOT))
    for patch in patches:
        _run(["git", "apply", "--check", f"--directory={directory}", str(patch)])
        _run(["git", "apply", f"--directory={directory}", str(patch)])
    flags = [
        "-std=c++17", "-fPIC", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-Wno-pass-failed",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1", "-g", "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "clang++"), *flags, "-shared",
        f"-DTSCB_ALP_RD={int(algorithm == 'alp-rd')}",
        "-I", str(PROJECT_ROOT / "native/include"),
        "-I", str(target / "include"),
        str(adapter / "native/tscb_alp.cc"),
        *(str(target / "src" / name) for name in (
            "fastlanes_ffor.cpp", "fastlanes_unffor.cpp",
            "fastlanes_generated_ffor.cpp", "fastlanes_generated_unffor.cpp",
        )),
        "-o", str(output),
    ]


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
        "-std=c++17", "-fPIC", "-Wall", "-Wextra", "-Werror",
        "-Wno-vla", "-Wno-parentheses", "-Wno-unused-parameter",
        "-Wno-reorder", "-Wno-sign-compare",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
        ]
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
        os.environ.get("CXX", "c++"), *flags, "-shared", "-Wl,--no-undefined",
        f"-DTSCB_SERF_XOR={int(algorithm == 'serf-xor')}",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(target / "src"),
        str(adapter / "native/tscb_serf.cc"),
        *(str(target / "src" / name) for name in source_names),
        "-o", str(output),
    ]


def _zfp_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "zfp"
    vendor = adapter / "vendor" / "zfp"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_names = (
        "zfp.c", "bitstream.c",
        "encode1f.c", "encode1d.c", "encode1i.c", "encode1l.c",
        "decode1f.c", "decode1d.c", "decode1i.c", "decode1l.c",
        "encode2f.c", "encode2d.c", "encode2i.c", "encode2l.c",
        "decode2f.c", "decode2d.c", "decode2i.c", "decode2l.c",
        "encode3f.c", "encode3d.c", "encode3i.c", "encode3l.c",
        "decode3f.c", "decode3d.c", "decode3i.c", "decode3l.c",
        "encode4f.c", "encode4d.c", "encode4i.c", "encode4l.c",
        "decode4f.c", "decode4d.c", "decode4i.c", "decode4l.c",
    )
    return [
        os.environ.get("CC", "cc"), *flags, "-shared", "-Wl,--no-undefined",
        "-I", str(PROJECT_ROOT / "native/include"),
        "-I", str(vendor / "include"), "-I", str(vendor / "src"),
        str(adapter / "native/tscb_zfp.c"),
        *(str(vendor / "src" / name) for name in source_names),
        "-lm", "-o", str(output),
    ]


def _neats_command(output: Path, profile: str, algorithm: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "neats"
    vendor = adapter / "vendor" / "neats"
    flags = [
        "-std=gnu++20", "-fPIC", "-Wall", "-Wextra", "-Wpedantic",
        "-Wno-comment", "-Wno-unknown-pragmas", "-fno-tree-vectorize",
        "-fno-tree-slp-vectorize",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"), *flags, "-shared", "-Wl,--no-undefined",
        f"-DTSCB_NEATS={int(algorithm == 'neats-lossless-i64')}",
        "-I", str(PROJECT_ROOT / "native/include"),
        "-I", str(vendor / "include"),
        "-I", str(vendor / "lib/sdsl-lite/include"),
        "-I", str(vendor / "lib/sux"),
        str(adapter / "native/tscb_neats.cc"),
        "-o", str(output),
    ]


def _delta_varint_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "delta_varint"
    vendor = adapter / "vendor" / "varint"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-parameter", "-Wno-stringop-overread",
             "-Wno-stringop-overflow", "-Wl,-Bsymbolic-functions"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += ["-O1", "-g", "-fno-omit-frame-pointer",
                  "-fsanitize=address,undefined"]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CC", "cc"), *flags, "-shared",
        "-I", str(PROJECT_ROOT / "native/include"), "-I", str(vendor),
        str(adapter / "native/tscb_delta_varint.c"),
        str(vendor / "varintDelta.c"), str(vendor / "varintExternal.c"),
        "-o", str(output),
    ]


def _build(algorithm: str, profile: str) -> dict[str, Any]:
    directory_name = algorithm.replace("-", "_")
    output_dir = PROJECT_ROOT / "build" / "adapters" / directory_name / profile
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"libtscb_{directory_name}.so"
    dependency_evidence: dict[str, Any] = {}
    dependency_log = ""
    if algorithm == "delta-varint":
        command = _delta_varint_command(output, profile)
        dependency_evidence = {
            "upstream_repository": "https://github.com/mattsta/varint",
            "upstream_commit": "81ba89cd76f079649de49f5726f50f8a1344b21d",
            "source_closure": [
                "adapters/delta_varint/vendor/varint/varint.h",
                "adapters/delta_varint/vendor/varint/varintExternal.h",
                "adapters/delta_varint/vendor/varint/varintExternal.c",
                "adapters/delta_varint/vendor/varint/varintDelta.h",
                "adapters/delta_varint/vendor/varint/varintDelta.c",
                "adapters/delta_varint/vendor/varint/endianIsLittle.h",
            ],
            "variant": "SIGNED_INT64_BASE_PLUS_ZIGZAG_DELTA_EXTERNAL_WIDTH",
        }
    elif algorithm in ("serf-qt", "serf-xor"):
        command = _serf_command(output, profile, algorithm)
        dependency_evidence = {
            "upstream_commit": "b38450b56825eabc96be8e25d6880127dc688c95",
            "patch_sha256": [
                _sha256(PROJECT_ROOT / "adapters/serf/patches" / name)
                for name in (
                    "0001-defined-bit-operations.patch",
                    "0002-prefix-mask-bounds.patch",
                    "0003-input-bit-stream-guard.patch",
                )
            ],
            "patched_translation_unit_sha256": [
                _sha256(output_dir / "serf/src/utils" / name)
                for name in (
                    "double.h", "float.h", "zig_zag_codec.h",
                    "output_bit_stream.cc", "input_bit_stream.cc",
                    "serf_utils_32.cc", "serf_utils_64.cc",
                )
            ],
        }
    elif algorithm in ("neats-lossless-i64", "leats-lossless-i64"):
        command = _neats_command(output, profile, algorithm)
        dependency_evidence = {
            "upstream_commit": "2d804ff492e45222e841dc1a50904476fa64f4a0",
            "variant": "NEATS_NONLINEAR" if algorithm.startswith("neats") else "LEATS_LINEAR",
            "isa": "SCALAR_NO_AUTOVECTORIZATION",
            "patch_sha256": [
                _sha256(PROJECT_ROOT / "adapters/neats/patches" / name)
                for name in (
                    "0001-gcc11-scalar-compatibility.patch",
                    "0002-leats-serialization.patch",
                    "0003-leats-predictor-precision.patch",
                )
            ],
        }
    elif algorithm == "zfp-accuracy-1d":
        command = _zfp_command(output, profile)
        dependency_evidence = {
            "upstream_commit": "c0c2c40b30d99f1787664b51c593fb6e0d729253",
            "mode": "FIXED_ACCURACY",
            "topology": "1D_PER_COLUMN",
            "backend": "SERIAL_CPU",
        }
    elif algorithm in ("alp", "alp-rd"):
        command = _alp_command(output, profile, algorithm)
        dependency_evidence = {
            "patch_sha256": [
                _sha256(PROJECT_ROOT / "adapters/alp/patches" / name)
                for name in (
                    "0001-float-factor-array-bound.patch",
                    "0002-decoder-multiply-domain.patch",
                    "0003-encoded-integer-range.patch",
                )
            ],
            "patched_encoder_sha256": _sha256(
                output_dir / "alp/include/alp/encoder.hpp"
            ),
            "source_encoder_sha256": _sha256(
                PROJECT_ROOT / "adapters/alp/vendor/alp/include/alp/encoder.hpp"
            ),
        }
    elif algorithm == "lz4-frame":
        command = _lz4_command(output, profile)
    elif algorithm in ("huff0", "fse"):
        command = _entropy_command(output, profile, algorithm)
    elif algorithm in ("sprintz-delta-u8", "sprintz-fire-u8"):
        command = _sprintz_command(output, profile, algorithm)
        dependency_evidence = {
            "patch_sha256": _sha256(
                PROJECT_ROOT / "adapters/sprintz/patches/0001-lowdim-byte-safety.patch"
            ),
            "patched_translation_unit_sha256": [
                _sha256(output_dir / "sprintz" / name)
                for name in ("sprintz_delta_lowdim.cpp", "sprintz_xff_lowdim.cpp")
            ],
        }
    elif algorithm in ("sprintz-delta", "sprintz-fire"):
        command = _sprintz_full_command(output, profile, algorithm)
        dependency_evidence = {
            "patch_sha256": [
                _sha256(PROJECT_ROOT / "adapters/sprintz/patches" / name)
                for name in (
                    "0001-lowdim-byte-safety.patch",
                    "0002-generic-allocation-safety.patch",
                )
            ],
            "patched_translation_unit_sha256": [
                _sha256(output_dir / "sprintz" / name)
                for name in (
                    "sprintz.cpp", "sprintz_delta_lowdim.cpp", "sprintz_xff_lowdim.cpp",
                    "sprintz_delta_rle.cpp", "sprintz_xff_rle.cpp", "format.cpp",
                )
            ],
        }
    elif algorithm == "sprintz-fire-huff0":
        command = _sprintz_fire_huff0_command(output, profile)
        dependency_evidence = {
            "source_artifact_dependencies": [
                "sprintz-lzbench",
                "entropy-fse-benchmark",
            ],
            "patch_sha256": [
                _sha256(PROJECT_ROOT / "adapters/sprintz/patches" / name)
                for name in (
                    "0001-lowdim-byte-safety.patch",
                    "0002-generic-allocation-safety.patch",
                    "0003-fire-prediction-overflow.patch",
                )
            ],
            "patched_translation_unit_sha256": [
                _sha256(output_dir / "sprintz" / name)
                for name in (
                    "sprintz.cpp", "sprintz_delta_lowdim.cpp", "sprintz_xff_lowdim.cpp",
                    "sprintz_delta_rle.cpp", "sprintz_xff_rle.cpp", "format.cpp",
                )
            ],
        }
    elif algorithm == "zstd-frame":
        command = _zstd_command(output, profile)
    elif algorithm == "snappy-raw":
        command = _snappy_command(output, profile)
    elif algorithm == "lzsse8-raw":
        command = _lzsse8_command(output, profile)
        dependency_evidence = {
            "patch_sha256": _sha256(
                PROJECT_ROOT / "adapters/lzsse8_raw/patches"
                / "0001-allocation-unaligned-pointer-safety.patch"
            ),
            "patched_translation_unit_sha256": _sha256(output_dir / "lzsse8.cpp"),
            "source_translation_unit_sha256": _sha256(
                PROJECT_ROOT / "adapters/lzsse8_raw/vendor/lzsse/lzsse8/lzsse8.cpp"
            ),
        }
    elif algorithm == "lzsse2-raw":
        command = _lzsse2_command(output, profile)
        dependency_evidence = {
            "patch_sha256": _sha256(
                PROJECT_ROOT / "adapters/lzsse2_raw/patches"
                / "0001-allocation-unaligned-pointer-safety.patch"
            ),
            "patched_translation_unit_sha256": _sha256(output_dir / "lzsse2.cpp"),
            "source_translation_unit_sha256": _sha256(
                PROJECT_ROOT / "adapters/lzsse2_raw/vendor/lzsse/lzsse2/lzsse2.cpp"
            ),
        }
    elif algorithm == "brotli-stream":
        command = _brotli_command(output, profile)
    elif algorithm == "deflate-zlib":
        command = _deflate_zlib_command(output, profile)
    elif algorithm == "bzip2-stream":
        command = _bzip2_command(output, profile)
    elif algorithm == "lzss-raw":
        command, dependency_evidence, dependency_log = _lzss_command(output, profile)
    elif algorithm == "lzss-dipperstein-c":
        command = _lzss_dipperstein_command(output, profile)
        vendor = PROJECT_ROOT / "adapters/lzss_dipperstein/vendor/lzss"
        patch = (
            PROJECT_ROOT / "adapters/lzss_dipperstein/patches"
            / "0001-binary-tree-sentinel-bounds.patch"
        )
        dependency_evidence = {
            "upstream_commit": "65b6882ff1cc225f9c6fcd947def7b1adb21d578",
            "bitfile_commit": "2e6132f75cbe16842a9ab81af7756ed9ac1cdbe0",
            "patch_sha256": _sha256(patch),
            "patched_tree_sha256": _sha256(output_dir / "tree.c"),
            "source_tree_sha256": _sha256(vendor / "tree.c"),
            "unmodified_source_sha256": [
                _sha256(vendor / name)
                for name in ("lzss.c", "tree.c", "bitfile/bitfile.c")
            ],
        }
    elif algorithm == "xz-stream":
        command, dependency_evidence, dependency_log = _xz_command(output, profile)
    else:
        raise ValueError(f"unknown algorithm: {algorithm}")
    log = dependency_log + _run(command)
    command_document = {
        "schema_version": "tscb.compile-command.v1",
        "profile": profile,
        "command": command,
        **dependency_evidence,
    }
    command_bytes = json.dumps(
        command_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if dependency_evidence:
        (output_dir / "compile-command.json").write_bytes(command_bytes + b"\n")
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "algorithm": algorithm,
        "profile": profile,
        "artifact": str(output.relative_to(PROJECT_ROOT)),
        "artifact_sha256": _sha256(output),
        "compile_commands_sha256": hashlib.sha256(command_bytes).hexdigest(),
        "compiler": _run([command[0], "--version"]).splitlines()[0],
        "command_display": shlex.join(command),
        "build_log": log,
    }
    record_path = output_dir / "build-record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a frozen source codec adapter")
    parser.add_argument(
        "algorithm",
        choices=(
            "huff0", "fse", "sprintz-delta-u8", "sprintz-fire-u8",
            "sprintz-delta", "sprintz-fire", "sprintz-fire-huff0",
            "lz4-frame", "zstd-frame", "snappy-raw", "lzsse2-raw", "brotli-stream",
            "deflate-zlib", "bzip2-stream", "xz-stream", "lzss-raw",
            "lzss-dipperstein-c", "lzsse8-raw", "alp", "alp-rd",
            "serf-qt", "serf-xor", "zfp-accuracy-1d",
            "neats-lossless-i64", "leats-lossless-i64", "delta-varint"
        ),
    )
    parser.add_argument("--profile", choices=("release", "sanitizer", "all"), default="release")
    arguments = parser.parse_args()
    profiles = ("release", "sanitizer") if arguments.profile == "all" else (arguments.profile,)
    records = [_build(arguments.algorithm, item) for item in profiles]
    print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
