# Prometheus XOR2 Chunk rewrite status

Gates G0-G6 are complete for the first-batch `prometheus-xor2-chunk`
candidate and the rewrite-only terminal status is `REWRITE_DONE`. The source
closure is frozen under the matching `Source` directory. The executable Go
oracle, 13 physical golden chunks and the real-dataset plan freeze the joint
timestamp/value/start-timestamp contract.

The critical format boundary is one interleaved stream: timestamp and value
share control prefixes, while optional start-timestamp state uses the header and
varbit deltas defined by the same chunk. These components must not be ported as
independent codecs. Benchmark integration remains a separate future task.

The canonical C++17 API, independent `pxor2_*_v1` C ABI, native and sanitizer
tests, real-dataset results, scalar CORE baseline and x86_64/AArch64 release
evidence are under this directory. No adapter, registry entry or Benchmark
experiment configuration is included.
