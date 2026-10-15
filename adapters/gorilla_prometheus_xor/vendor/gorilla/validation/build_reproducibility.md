# Reproducible build evidence

**BIT_FOR_BIT_REPRODUCIBLE**：repro-c / repro-d 两个事先不存在的独立构建
目录、相同最终源码、GNU 11.4.0/CMake 3.22.1、Release -O3 -DNDEBUG；
无 fast-math、FP contraction off、无 march=native。四个产物 SHA-256 全相同，
并与交付 release 构建一致。

完整原始 compile_commands 两份及各自 hash 位于构建目录与
reproducibility.json；其构建目录字段不同，目标产物逐字节相同。源/编译器/
链接器/glibc/环境 digest 和命令记录在 environment.json、repro-c.log、
repro-d.log。源码/参考源/驱动与运行 artifact hash 另由 RELEASE_MANIFEST.json
绑定；文档、缓存和非构建脚本不是生产 translation-unit 依赖。

独立 C++ 构建入口 CMakeLists.txt 不依赖原语言、Bench 源码、adapter、registry
或运行目录。参考 Go 1.26.0、AArch64 cross toolchain 仅作 oracle/验证；
其固定 archive/package URLs 和 SHA-256 在 Source 包清单中。
- `libgorilla.a`: `2bfd78f2bc4042bcd1c29589581ea42f32aaf34822ea46e1d1238fbe3a55a087`
- `gorilla_cli`: `364150baeb6fe08ac001020f86267be029e6fcafd9204e9cde4bf55171cb667c`
- `gorilla_tests`: `c4571a4c4da7d620aedca842d9728dc8a1186276fe707eb0995394942767aaa6`
- `gorilla_bench`: `9ce664167b0085f4346d32baf7eafd8205123e30da4d135fd38d47b6c8546abe`
