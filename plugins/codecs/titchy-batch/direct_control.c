/* Independent caller of the frozen Titchy C11 batch ABI. */
#include "titchy.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { COUNT_CAP = 8192, RAW_CAP = COUNT_CAP * 8, WIRE_CAP = 262144 };

static int load(const char *path, unsigned char *data, size_t capacity, size_t *n) {
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    *n = fread(data, 1, capacity, file);
    const int complete = fgetc(file) == EOF && !ferror(file);
    return fclose(file) == 0 && complete;
}

static int save(const char *path, const unsigned char *data, size_t n) {
    FILE *file = fopen(path, "wbx");
    if (!file) return 0;
    const int wrote = fwrite(data, 1, n, file) == n;
    return fclose(file) == 0 && wrote;
}

int main(int argc, char **argv) {
    if (argc != 4) return 2;
    char *end;
    const unsigned long bits = strtoul(argv[1], &end, 10);
    if (*end || (bits != 8 && bits != 16 && bits != 32 && bits != 64)) return 2;
    const size_t width = bits / 8;
    unsigned char native[WIRE_CAP], raw[RAW_CAP];
    uint64_t input[COUNT_CAP], output[COUNT_CAP];
    size_t size, written = 0, got = 0;
    if (!load(argv[2], raw, sizeof raw, &size) || size % width || size / width > COUNT_CAP) return 3;
    const size_t n = size / width;
    for (size_t i = 0; i < n; ++i) {
        input[i] = 0;
        for (size_t b = 0; b < width; ++b) input[i] |= (uint64_t)raw[i*width+b] << (b*8);
    }
    const titchy_config cfg = {(uint8_t)bits, 4, 1000, 0, .25, UINT64_MAX};
    const size_t bound = titchy_bound(n, &cfg);
    if (!bound || bound > sizeof native ||
        titchy_c_encode(input, n, &cfg, native, bound, &written) != TITCHY_OK ||
        !written || written > bound ||
        titchy_c_decode(native, written, output, n, n, &got) != TITCHY_OK || got != n ||
        memcmp(input, output, n*sizeof input[0]) || !save(argv[3], native, written)) return 4;
    int encode_cap = 0, decode_cap = 0, decode_quota = 0;
    if (n) {
        unsigned char too_small[1];
        got = 999;
        encode_cap = titchy_c_encode(input, n, &cfg, too_small, sizeof too_small, &got);
        if (encode_cap != TITCHY_CAPACITY || got) return 5;
        got = 999;
        decode_cap = titchy_c_decode(native, written, output, n-1, n, &got);
        if (decode_cap != TITCHY_CAPACITY || got) return 5;
        got = 999;
        decode_quota = titchy_c_decode(native, written, output, n, n-1, &got);
        if (decode_quota != TITCHY_CAPACITY || got) return 5;
    }
    return printf("{\"count\":%zu,\"bound\":%zu,\"bytes\":%zu," 
                  "\"encode_capacity_status\":%d,\"decode_capacity_status\":%d,\"decode_quota_status\":%d}\n",
                  n, bound, written, encode_cap, decode_cap, decode_quota) < 0 ? 6 : 0;
}
