# Independent benchmark audit baseline (frozen before project content review)

This is a project-independent design test, not a statement of any repository's implementation.

1. Start with user decisions and research questions, then choose tasks and representative corpora; an algorithm inventory is an integration backlog, not a benchmark definition.
2. Separate logical task/recovery semantics, data representation, algorithm mechanism, implementation/backend/build, artifact/dependencies, execution protocol, and analysis/reporting.
3. Permit at least API/primitive research and complete-object research with separately declared boundaries. A fixed decoder protocol or externally persisted schema can be legitimate; hidden original-input metadata cannot.
4. Distinguish bitwise equality, semantic equality (including null slots), and bounded/empirical lossy fidelity. Timestamp topology and IEEE exceptional values need explicit policies.
5. Treat correctness/contract fixtures separately from representative evaluation corpora. Freeze source, sampling, weighting, splits, and transformations; prevent correlated windows or repeated samples from masquerading as independent datasets.
6. Compare a shared task at declared fidelity/resource/measurement conditions. Do not infer comparability from a method-family label; do not shrink the cohort or corpus after seeing outcomes.
7. Expose configuration policies: fixed/default, development-set tuned, and oracle research. Freeze tuning budgets and keep training/development/test independent.
8. Report raw payload, framing/schema, index, validity, model/dictionary and dependency costs at the selected boundary. Shared costs require an explicit deployment/amortization scenario; no implicit zero-cost dependencies.
9. Distinguish one-object batch, batch of objects, independent blocks, persistent streaming, native internal parallelism, framework workers and experiment concurrency; declare actual implementation path, not requested labels alone.
10. Define timer start/end and setup/allocation/FFI/cache state. External wall-clock timing can validly measure API/object latency; in-code timers are not a universal gate. Measure instrumentation perturbation and asynchronous completion when applicable.
11. Separate inner iterations from independent process/session repetitions. Pilot, blocked randomization/paired scheduling, stable observation units and declared stopping/precision policies precede statistical summaries; there is no universal mandatory repeat count.
12. Preserve raw observations, uncertainty, failed/unsupported/timeout states and denominators. Aggregate by a declared estimand and source weights; do not treat chunks, repetitions or configurations as independent datasets.
13. Separate implementation identity from correctness, source fidelity, format interoperability and performance claim scope. Bitstream identity is only necessary for a compatibility/reproduction claim that requires it.
14. A small executable core specification should enforce contracts and run planning; plugins for codecs, transforms, validators, metrics, datasets and reports should be independently testable. The public workflow must make unsupported reasons and comparable groups understandable.
15. A release needs executable conformance evidence, multiple applicable methods on multiple frozen shared datasets, transparent limits and reproducible artifacts. Support breadth and comparison coverage remain separate measures. Stage optional profiles rather than execute a full Cartesian product.

External facts actually read by the root before repository content review:
- Chiarot & Silvestri survey arXiv 2101.08784v2: compares published results, not a unified rerun; useful taxonomy is not an experimental protocol.
- SPEC CPU2017 run rules: fixed workloads/disclosure, base vs peak and study deviations; repeat rules specific to this benchmark, not universal.
- Apache Arrow Columnar format v1.5: logical types vs physical buffers, validity, dictionary dependencies, stream/file distinctions; bytes under null slots unspecified.
- lzbench official README: in-memory compression/decompression verification, source compilation, explicit 4MB independent-block threading with changed ratios and memory-bandwidth baseline.

Independent engineering inferences above are recommendations, not requirements allegedly imposed by any single external source. Additional parallel external research is retained separately with its access depth.
