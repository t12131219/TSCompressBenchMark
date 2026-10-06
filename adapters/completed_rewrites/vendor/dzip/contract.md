# DZip contract v1 (frozen before native implementation)

Canonical source: mohit1997/DZip at b52ed99687919a744dfdc3dc7a968b2331ee7102.
Compatibility target: SEMANTIC. Both bootstrap-only and combined CPU codecs are required.

Input preprocessing follows the original latin-1 text reader, universal newline conversion,
sorted alphabet, integer symbol mapping and stride-1 windows of 64 symbols. The original
decoder writes locale-default text (UTF-8 on this host), so it does not preserve arbitrary
latin-1 bytes or CRLF bytes. Native raw-byte input is an explicitly named additional profile;
source differential uses the same normalized ASCII text/symbol inputs. Empty and short
streams are outside the original 65-or-more-symbol pipeline; native may encode them through
a separately identified safe extension. Alphabet 9 is unsupported in original biGRU_big and
biGRU_jump and must be explicitly rejected in the source-compatible model profile.

CPU combined model consists of two bidirectional reset-after GRUs, selected time positions
15/31/47/63, an embedding/dense/residual supporter and final softmax. CPU GRUs use the Keras
default hard_sigmoid recurrent activation and tanh candidate. GPU CuDNNGRU uses sigmoid:
the coding-gpu estimator is a distinct profile, not a source bitstream encoder.

First 64 symbols use uniform float64 frequencies. Subsequent probabilities are float32;
`prob*10000000+1` promotes to float64 in NumPy 1.16.4, then float64 prefix summation
and truncation into integer cumulative counts apply. Arithmetic state is 32-bit inclusive
low/high. Finish writes one 1 bit; padding and implicit zero bits on decoder EOF are source
semantics. Original raw .dzip lacks length, alphabet and model; those are counted side files.

Combined mode predicts all 128 successive targets before one source TensorFlow Adam update.
The complete batch uses overlapping windows. Tail symbols never trigger a partial update.
CPU Adam uses lr=5e-4, beta1=.9, beta2=.999, epsilon=1e-8 and loss in bits
`categorical_crossentropy/log(2)`. The CPU implementation updates shared backbone weights;
no bootstrap freezing may be added to this profile. The GPU estimation script freezes the
bootstrap layers and uses beta1=0; it cannot be substituted for the CPU encoder.

Native inference and gradient/updated-weight differential tolerances are fixed before code:
absolute 2e-6 plus relative 2e-5 for probabilities; absolute 2e-6 plus relative 2e-4 for
gradients/updated weights over three Adam steps. These do not imply matching quantized
cumulative tables. Native self-decode must restore input exactly using its declared numerical
profile and identically initialized state; source probability differential and source raw
arithmetic-table replay are separate witnesses. No source/new cross-decode claim is made
for learned numerical profiles until proven, and no tolerance may be increased after failure.

Model import/export is explicit. Full initial graph/weights state, alphabet, length, mode,
numerical profile, arithmetic payload, framing and BSC model compression all count in
FinalBits; no oracle, seed or model state is free. Initial supporter state is stored or
reproducibly initialized by a declared native method. Test-only source export is not a
deployed dependency. Bootstrap training, checkpoint selection and data-dependent training
cost remain visible as preprocessing; importing a checkpoint is not evidence that native
bootstrap training is implemented. Until all required capabilities pass, status is IN_PROGRESS.

Separate native handles must be safe concurrently. Borrowed input is immutable; exact
capacity query, bound-1, canaries, zero overread, resource caps, malformed-model/stream
rejection and stable finalize/reset are required before release. Native is C++17; no Python,
Keras or TensorFlow runtime may execute in its production path. Retained native libbsc and
audited matrix/HDF5 libraries are allowed with their provenance recorded.

License workflow: user decision ../../USER_DECISIONS.md applies. Provenance and known
notices remain; no unknown upstream grant is invented. No framework adapter is in scope.

Pre-entropy-implementation correction on 2026-10-04: direct execution in the locked
NumPy runtime established that multiplication by the Python integer 10000000 promotes
float32 probability arrays to float64. The first draft described this promotion incorrectly;
the formula and tolerances are unchanged. Native arithmetic implementation follows this
observed dtype, not a float32 substitute. The direct observation is recorded separately.
