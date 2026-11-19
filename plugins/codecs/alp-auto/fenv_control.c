/* Call the frozen ALP C ABI under a measured non-default FP environment. */
#include <fenv.h>
#include <stdio.h>
#include <string.h>
#include "alp_native.h"

enum { CAPACITY = 16384 };

static int load(const char *path, void *data, size_t capacity, size_t *size) {
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    *size = fread(data, 1, capacity, file);
    const int complete = fgetc(file) == EOF && !ferror(file);
    return fclose(file) == 0 && complete;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    unsigned char raw[CAPACITY], frame[CAPACITY], out[CAPACITY];
    size_t raw_bytes, frame_bytes, enc = 999, dec = 999;
    if (!load(argv[1], raw, sizeof raw, &raw_bytes) || !raw_bytes || raw_bytes % 8 ||
        !load(argv[2], frame, sizeof frame, &frame_bytes) || !frame_bytes) return 3;
    const size_t count = raw_bytes / 8;
    const int before = fegetround();
    const size_t bound = alpn_compress_bound(count, 64);
    unsigned width;
    size_t claimed;
    if (before != FE_TONEAREST || !bound || bound > sizeof out ||
        alpn_inspect(frame, frame_bytes, &width, &claimed) != ALPN_OK || width != 64 || claimed != count) return 4;
    if (fesetround(FE_DOWNWARD) != 0) return 5;
    const int changed = fegetround();
    const int e = alpn_compress(raw, count, 64, ALPN_AUTO, out, sizeof out, &enc, NULL);
    const int e_reason = strcmp(alpn_last_error(), "compression requires FE_TONEAREST") == 0;
    const int d = alpn_decompress_ex(frame, frame_bytes, count, out, count, &dec, ALPN_SCALAR, NULL);
    const int d_reason = strcmp(alpn_last_error(), "decompression requires FE_TONEAREST") == 0;
    if (fesetround(before) != 0) return 6;
    const int after = fegetround();
    return printf("{\"before\":%d,\"changed\":%d,\"after\":%d,\"rows\":%zu,"
                  "\"encode\":{\"status\":%d,\"written\":%zu,\"rounding_diagnostic_matches\":%d},"
                  "\"decode\":{\"status\":%d,\"written\":%zu,\"rounding_diagnostic_matches\":%d}}\n",
                  before, changed, after, count, e, enc, e_reason, d, dec, d_reason) < 0 ? 7 : 0;
}
