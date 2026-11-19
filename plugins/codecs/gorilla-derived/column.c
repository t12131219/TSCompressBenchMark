/* TSBench role-separated derivation of Unique gorilla-native/unique-v1
 * src/gorilla.c (Prometheus XORChunk). No g_sample or joint codec invocation.
 * The bit primitives are extracted verbatim at configure time. */
#include "column.h"
#include <limits.h>
#include <string.h>
#include "unique_gorilla_bits.inc"

_Static_assert(CHAR_BIT == 8, "8 bit bytes required");
#if !defined(BMK_GORILLA_TIMESTAMP) || (BMK_GORILLA_TIMESTAMP != 0 && BMK_GORILLA_TIMESTAMP != 1)
#error exactly one Gorilla column role must be selected
#endif

size_t bmk_gorilla_column_bound(size_t rows) {
    if (rows > BMK_GORILLA_COLUMN_ROWS) return 0;
#if BMK_GORILLA_TIMESTAMP
    const size_t bits = (rows ? 80 : 0) + (rows > 1 ? 80 + (rows - 2) * 68 : 0);
#else
    const size_t bits = rows ? 64 + (rows - 1) * 77 : 0;
#endif
    return 2 + (bits + 7) / 8;
}

size_t bmk_gorilla_column_encode(const uint8_t *column, size_t rows, uint8_t *out, size_t cap) {
    const size_t bound = bmk_gorilla_column_bound(rows);
    if (!bound || !out || cap < bound || (rows && !column)) return 0;
    out[0] = (uint8_t)(rows >> 8);
    out[1] = (uint8_t)rows;
    writer w = {out + 2, 0, 0};
    uint64_t prev = 0;
#if BMK_GORILLA_TIMESTAMP
    uint64_t prev_delta = 0;
#else
    unsigned lz = 255, tz = 0;
#endif
    for (size_t i = 0; i < rows; ++i) {
        uint64_t word;
        memcpy(&word, column + i * 8, 8);
#if BMK_GORILLA_TIMESTAMP
        uint64_t delta = word - prev;
        if (!i) uvarint(&w, (word << 1) ^ ((word >> 63) ? UINT64_MAX : 0));
        else if (i == 1) uvarint(&w, delta);
        else {
            const uint64_t dod = delta - prev_delta;
            if (!dod) put(&w, 0, 1);
            else if (fits(dod, 14)) { put(&w, 2, 2); put(&w, dod, 14); }
            else if (fits(dod, 17)) { put(&w, 6, 3); put(&w, dod, 17); }
            else if (fits(dod, 20)) { put(&w, 14, 4); put(&w, dod, 20); }
            else { put(&w, 15, 4); put(&w, dod, 64); }
        }
        prev_delta = delta;
#else
        if (!i) put(&w, word, 64);
        else {
            const uint64_t x = prev ^ word;
            if (!x) put(&w, 0, 1);
            else {
                unsigned a = leading(x), b = trailing(x);
                if (a > 31) a = 31;
                if (lz != 255 && a >= lz && b >= tz) {
                    put(&w, 2, 2); put(&w, x >> tz, 64 - lz - tz);
                } else {
                    const unsigned sig = 64 - a - b;
                    put(&w, 3, 2); put(&w, a, 5); put(&w, sig, 6);
                    put(&w, x >> b, sig);
                    lz = a; tz = b;
                }
            }
        }
#endif
        prev = word;
    }
    while (w.used) {
        *w.p++ = (uint8_t)(w.acc >> 56); w.acc <<= 8;
        w.used = w.used > 8 ? w.used - 8 : 0;
    }
    return (size_t)(w.p - out);
}

int bmk_gorilla_column_decode(const uint8_t *payload, size_t bytes, size_t rows, uint8_t *column) {
    if (!payload || bytes < 2 || bytes > bmk_gorilla_column_bound(rows) ||
        (((size_t)payload[0] << 8) | payload[1]) != rows || (rows && !column)) return 0;
    reader r = {payload + 2, bytes - 2, (bytes - 2) * 8, 0, 0, 0};
    uint64_t word = 0;
#if BMK_GORILLA_TIMESTAMP
    uint64_t delta = 0;
#else
    unsigned lz = 255, tz = 0;
#endif
    for (size_t i = 0; i < rows; ++i) {
#if BMK_GORILLA_TIMESTAMP
        if (!i) {
            const uint64_t zig = get_uvarint(&r);
            word = (zig >> 1) ^ ((zig & 1) ? UINT64_MAX : 0);
        } else {
            if (i == 1) delta = get_uvarint(&r);
            else {
                unsigned ones = 0;
                while (ones < 4 && get(&r, 1)) ++ones;
                if (ones) {
                    const unsigned bits = ones == 1 ? 14 : ones == 2 ? 17 : ones == 3 ? 20 : 64;
                    uint64_t dod = get(&r, bits);
                    if (bits != 64 && dod > (UINT64_C(1) << (bits - 1))) dod -= UINT64_C(1) << bits;
                    delta += dod;
                }
            }
            word += delta;
        }
#else
        if (!i) word = get(&r, 64);
        else if (get(&r, 1)) {
            unsigned sig;
            if (get(&r, 1)) {
                lz = (unsigned)get(&r, 5); sig = (unsigned)get(&r, 6);
                if (!sig) sig = 64;
                if (lz + sig > 64) return 0;
                tz = 64 - lz - sig;
            } else {
                if (lz == 255) return 0;
                sig = 64 - lz - tz;
            }
            const uint64_t x = get(&r, sig);
            if (!x) return 0;
            word ^= x << tz;
        }
#endif
        if (r.bad) return 0;
        memcpy(column + i * 8, &word, 8);
    }
    return r.remaining < 8 && get(&r, (unsigned)r.remaining) == 0 && !r.bad;
}
