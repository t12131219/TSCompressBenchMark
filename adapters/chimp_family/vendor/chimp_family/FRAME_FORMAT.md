# CFP1 version1

Little endian integers and IEEE bits; total physical size32+payload+4.

| Offset | Bytes | Meaning |
|---|---:|---|
|0|4|ASCII CFP1|
|4|1|version1|
|5|1|method1..11 (see header enum)|
|6|2|reserved zero|
|8|4|history N; used by ChimpN/NoIndex/N32|
|12|4|float epsilon; used by lossy methods|
|16|8|original input sample count|
|24|8|payload byte length|
|32|variable|original Chimp/FPC raw payload or new segment payload|
|end-4|4|CRC32/ISO-HDLC of all preceding frame bytes|

Segment record52 bytes: signed start/end timestamps8+8, binary64 a/b/aMin/aMax8*4, binary32 quantized_b4. Nonquantized min/max/b fields zero. PMC uses a=0 and b=float midpoint promoted to double. PMC reconstruction returns float(b) directly, preserving signed zero; other reconstruction emits float(a*t+b) at each integer timestamp, inclusive. Quantized time is sample index. Source NaN signs/payloads are unspecified for arithmetic results and compared semantically; nonfinite coefficients are retained only in source-compatible research mode. Strict encoding checks actual reconstructed ABS epsilon and rejects failures. No arbitrary strict lossy bound is asserted for a source-compatible frame.

Decoder limits1,048,576 input values, segments and reconstructed dense values, N power-of-two1..65536. Exact frame size/CRC/version/reserved/algorithm/bit widths/padding/count validated. Checksum detects corruption, provides no authentication. All metadata required for cold decode is present. Raw stateful FPC additionally requires call count and matching predictor state; it is not a self-contained frame. Binary64 NaNs canonicalized by FPC source policy; Chimp's canonical positive NaN is reserved EOF.

FinalBits=value/model payload physical bytes*8 + metadata256 + checksum32. Raw Chimp meaningful_bits includes the EOF sentinel and terminal false bit; padding0..7 bits is included in physical payload. Odd FPC padding is included in physical raw bytes. No external_side_information_bits for CFP1.
