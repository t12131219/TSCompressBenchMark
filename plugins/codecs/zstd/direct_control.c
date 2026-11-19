/* Reference path through the vendored Zstd API, bypassing both TSBench ABI and ln_compress. */
#include <stdio.h>
#include <string.h>
#include "zstd.h"

enum { BLOCK = 65536, WIRE = 66000 };

static int load(const char *path, void *data, size_t cap, size_t *size) {
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    *size = fread(data, 1, cap, file);
    const int complete = fgetc(file) == EOF && !ferror(file);
    return fclose(file) == 0 && complete;
}

int main(int argc, char **argv) {
    if (argc != 4 || strcmp(argv[1], "encode") != 0) return 2;
    unsigned char raw[BLOCK], compressed[WIRE];
    size_t n;
    if (!load(argv[2], raw, BLOCK, &n) || ZSTD_compressBound(n) > WIRE) return 3;
    const size_t size = ZSTD_compress(compressed, WIRE, raw, n, 3);
    if (!size || ZSTD_isError(size)) return 4;
    FILE *file = fopen(argv[3], "wbx");
    if (!file) return 5;
    const int wrote = fwrite(compressed, 1, size, file) == size;
    if (fclose(file) != 0 || !wrote) return 5;
    return printf("{\"rows\":%zu}\n", n) < 0 ? 5 : 0;
}
