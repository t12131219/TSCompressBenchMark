# WaLLoC-1D algorithm contract v1

AlgorithmID `walloc-1d`; implementation `walloc-1d-translated-cpp-v1`;
ObjectLevel `P2_PIPELINE`; lossy float32 signal codec; CompatibilityTarget
`SEMANTIC`. Canonical source is danjacobellis/walloc at
`c75d1b05e03fd35f66f72fa6ae21d3bb51c2d7b2`. The complete original archive is
retained for provenance; execution closure is Codec1D, shared ToUniform/Round/
ToNormal, byte/channel helpers, audio_compression and train_stereo notebooks,
and their pinned dependencies. Codec2D, image-only utilities, residual 2D codecs,
unrelated experimental notebooks and documentation JavaScript are outside 1D.

Official checkpoints stereo_5x and stereo_20x are frozen at Hugging Face revision
`61880100b81243bf059966fbeccf7097b68fd994`, with strict key/shape validation and
SHA-256 in MODEL_MANIFEST.json. Both are required. Neutral WLMOD001 transport
contains only configuration and named float32 tensors, not an exported execution
graph. Native initialization and training must also work without Python/model
export. Original pickle files are oracle input only; production imports the
documented neutral format and fails on malformed, nonfinite or incompatible state.

Input layout is contiguous B,C,L float32. Analysis repeats the one-level
periodized biorthogonal bior4.4 transform J times, arranging low/high adjacent
within each input channel. Odd one-level lengths duplicate the final sample.
Analysis and synthesis backward are the original custom AFB1D/SFB1D rules using
the stored filters, not a replacement generic convolution gradient. Filter
coefficients, order, float32 rounding, folding and rolling are part of the model.

The light encoder is Conv1d(kernel=1,padding=1). The alternate encoder is the
two stride-1 Oobleck blocks, with Snake1d, weight normalization and residual units
at dilations 1/3/9. Both add two latent positions. The decoder's two transposed
convolutions remove them. Hidden width is latent_dim*floor(Nd/latent_dim),
including the official 756-channel decoder (not 768). Post-filter is optional
Conv1d(kernel=129,padding=64). Clamp is [-0.5,0.5]. Source losses use the
unclamped reconstruction; waveform loss and transform loss must both be exposed.

For b=latent_bits, M=2^(b-1)-0.5-0.001 and s=(2^(b-1)-1)/1.85. ToUniform is
2*M*(NormalCDF(z/s)-0.5), with source float32 operator order. Eval uses
ties-to-even rounding; train adds independently sampled uniform [-0.5,0.5).
ToNormal clamps z/(2*M)+0.5 to [0.0001,0.9999], applies NormalICDF, then
multiplies by s. No quantization, post or clamp step may be bypassed silently.

Native naked-stage/forward API exposes these actual semantics, including source
shape errors. For the framed audio pipeline, each independent C,L object is
padded on the right with zeroes to a multiple of 65536, encoded, then its latent
length is padded to a multiple of 128. The latent is reshaped to C_lat,W,128,
offset by 2^(b-1), tiled as the original RGB helper and encoded using lossless
WebP 1.6.0, quality=80, method=4, exact=0. RGB tiling requires C_lat=3*n*n;
raw stage APIs do not impose this container-only condition. Decode untile,
subtract offset, remove latent padding, apply neural decoder, wavelet synthesis,
optional post-filter, original-length crop and clamp. Positive arbitrary lengths
are supported by this source notebook pipeline. Empty native frames are a named
safe extension; no source parity is claimed for source empty forward rejection.

WLFRA001 version 1 is a new self-contained format, not an upstream wire format.
It stores original/padded/latent lengths, complete neutral model, WebP payload,
checked lengths and CRC32 for the complete contents. Everything needed to decode
is inside the frame; normalization statistics, if normalization is requested,
must be retained as explicitly billed metadata. API input is the source-normalized
float32 signal, so normalization is exposed separately and is never an implicit
decoder dependency. FinalBits=8*entire_frame_bytes; model, payload, configuration,
all metadata, padding and checksum are billed. No free checkpoint/original input.
Self-decode is numerical reconstruction, not lossless waveform recovery. WebP
cross-decode must restore latent integers exactly in both directions. Original
notebooks keep lengths/model outside the WebP; a source WebP alone is not a
complete bitstream and cannot be presented as one.

Native graph and algorithm decisions are independently translated in C++17.
Existing native ATen/LibTorch 2.6.0+cu118 supplies audited tensor primitives,
autograd, convolution and optimizer kernels; libwebp is retained native container
code. No Python, diffusers, pytorch_wavelets, ONNX, TorchScript, JIT graph or
exported upstream forward program may run in production. This is native-core
reuse at primitive boundaries, not wrapping the original Python codec. The CPU
canonical target uses one intra/inter-op thread, strict FP compiler flags and
the frozen ATen kernels. It is not advertised as instruction-level scalar:
dependency CPU SIMD/dispatch remains declared. CUDA is a separate explicit
device variant and cannot silently fall back to CPU. Inference tensor kernels
can be reused across independent handles; shared global RNG and backend settings
must be locked, with independent handle state and documented thread limits.

Native training includes initialization, weight_norm g/v, train noise, both
source MSE losses, AdamW (betas=.9/.999,epsilon=1e-8,source lr/weight_decay),
gradient accumulation, cosine log10 warmup, ReduceLROnPlateau factor=.98,
source mixing/cropping/mean/max normalization and model/optimizer/RNG resume.
Checkpoint imports alone are not training parity. Source's 30 epochs/10000
steps and batch32/length524288 are exposed as configuration, not claimed to have
been run to convergence for acceptance. Training costs are reported separately;
test data is not used for fitting or hyperparameter selection. Source fixtures
for small training configurations are implementation witnesses, not new quality
models or substitutes for the official models. Any resource-driven accumulation
change needs its own gradient/update validation and disclosure.

Frozen numerical tolerances, before canonical implementation: CPU float32 stages
absolute 2e-5 plus relative 1e-4, waveform maximum absolute difference 2e-5;
CUDA stages absolute 5e-5 plus relative 2e-4, waveform maximum 5e-5. Quantized
latent and byte transport are EXACT for same-device source/native comparisons.
Training losses/output/gradients/parameters over three steps: absolute 3e-5 plus
relative 5e-4; RNG replay uses the pinned backend state, not a changed generator.
These are source/native consistency tolerances, not a universal reconstruction
error bound. Actual source/native distortion must be reported on every dataset.
No tolerance increase or changed quantization after failures. Cross-device
rounded decisions are measured and reported; CPU and CUDA are named numerical
profiles rather than assumed bitstream-identical models.

Native contract limits: model <=256 MiB, frame <=512 MiB, B<=32,C<=32,J<=10,
latent_dim<=1024, hidden widths<=2048, 2<=b<=8; checked tensor sizes and explicit
working-set admission limit. Borrowed input is immutable; truncated/OOB/duplicate
names/nonfinite models, bad checksums, inconsistent shapes, allocation overflow,
unsupported devices and resource exhaustion fail deterministically. Lifecycle,
capacity query, bound-1/canaries, stable finalize/reset, independent decode and
concurrent handle preflight precede release. GPU sanitizer and all required
capability tests remain mandatory; unavailable hardware is not a PASS.

The user decision in ../../USER_DECISIONS.md permits local audit/execution/rewrite
despite upstream NOASSERTION; provenance and third-party notices stay truthful.
No external publication or benchmark/framework integration is performed.
