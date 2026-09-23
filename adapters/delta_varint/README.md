# Delta + VarInt native primitive

This adapter vendors the minimal unmodified `mattsta/varint` source closure used
by its `varintDelta` tests and competition harness. The registered primitive is
signed little-endian `int64`: the first timestamp is ZigZag encoded, followed by
ZigZag modular deltas; every value carries an external 1-byte width.

The upstream payload is not self-describing. The TSCB adapter therefore charges
a versioned descriptor containing count, dtype, shape, and logical bits. It is
registered only as a P0 Timestamp primitive, not as a Value codec, resumable
stream, random-access format, or P1 standalone frame.

Build both reviewed profiles with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py delta-varint --profile all
```
