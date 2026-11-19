# Retain the frozen archive's default dynamic BMI2 policy. The option can be
# disabled explicitly for a portable build; this changes the build identity.
tsbench_frozen_source(FiniteStateEntropy reference)
tsbench_codec_module(tsbench_huff0_reference bmk_huff0_reference adapter.cpp reference)
