# Optimization decision

Status: `OPTIMIZATION_NOT_APPLICABLE` for this release.

The CORE scalar implementation encodes the fixed 8,192-sample case in a median
of about 0.539 ms and decodes it in about 15.76 us. Segmentation and inverse
correction carry are sequential, while the sorting-based aggregation already
uses early stopping. No measured profile evidence justifies a second code path.
The required upstream partitioned parallel compression stage is implemented in
the canonical C++ API and is not classified as an optional optimization. This
decision only says that no additional SIMD or alternative optimized codec path
is justified by current profiling.
