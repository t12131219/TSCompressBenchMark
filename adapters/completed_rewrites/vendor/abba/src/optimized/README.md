# Optimization decision

Status: `OPTIMIZATION_NOT_APPLICABLE` for this release.

The retained CKmeans kernel already uses its upstream SMAWK linear row-fill
path. Segmentation, symbol remapping, sequential rounding-correction carry and
reconstruction are order-dependent. The scalar canonical implementation
finishes an 8,192-sample encode in about 0.695 ms on the recorded host, and no
profile-backed hotspot justifies a second implementation. Adding SIMD or a
parallel variant without evidence would enlarge the semantic surface and
cross-platform risk.

