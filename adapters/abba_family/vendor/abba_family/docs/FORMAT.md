# AFS1 container, version 1

All header integers are unsigned little endian. Header: magic `AFS1` (4 bytes),
version 1 (u32), metadata length (u32), payload length (u64). Then UTF-8 JSON model
metadata, concatenated symbol streams, and CRC32 of all preceding bytes (u32).
No reserved flags are silently accepted; any header version other than 1 fails.
Exact file consumption is mandatory. Metadata is at most 16MiB, frame 256MiB.

Model metadata includes algorithm/version, configuration, alphabet, original
starts, single/batch shape, sample counts, and centers or complete QABBA signed
affine quantizer values, bit widths, scales and zero points. Image frames also
include shape, normalization mean/std. Each stream describes codec, count,
physical bytes and codec model. There are no external codebook files.

none/fixed use MSB-first symbol bits, zero low padding bits. Canonical Huffman
orders code lengths then numeric symbol IDs; Huffman1 carries per-context tables
and a fixed-width initial symbol. Equal-frequency source Huffman lengths use
first appearance; payload codes are package-owned canonical codes. LZW carries
codes with growing widths and checks exact decoded count. Byte codecs encode
little-endian 1-byte or 2-byte symbol IDs with pinned library versions.

Decoder checks total lengths/CRC before model or entropy allocations. It checks
stream lengths/counts, code lengths/oversubscription, symbol IDs, zero padding,
exact compressed input consumption and reconstructed length. CRC is accidental
corruption detection, not authentication; checksum-valid mutations are tested.

FinalBits = 8 × (20-byte header + metadata bytes + symbol payload bytes + 4-byte
CRC). External side information = 0. JSON metadata carries model data physically;
source theoretical estimates (which use different storage assumptions) never
replace this ledger. The format is package-owned and versioned independently of
all upstream classes.
