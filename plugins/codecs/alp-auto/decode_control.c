/* Bounded direct calls into the frozen ALP DSO, outside the plugin ABI. */
#include "alp_native.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { LIMIT = 1 << 20 };
static unsigned char in[LIMIT], out[LIMIT];
static const char unavailable[] = "requested decode backend unavailable for width/CPU/build";

static int load(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    *size = fread(in, 1, sizeof in, f);
    const int ok = fgetc(f) == EOF && !ferror(f) && *size != 0;
    return fclose(f) == 0 && ok;
}

static int save(const char *path, size_t size) {
    FILE *f = fopen(path, "wbx");
    if (!f) return 0;
    const int ok = fwrite(out, 1, size, f) == size;
    return fclose(f) == 0 && ok;
}

int main(int argc, char **argv) {
    size_t bytes, written = SIZE_MAX;
    if (argc != 4 || !load(argv[3], &bytes)) return 2;
    if (!strcmp(argv[1], "encode")) {
        const unsigned width = !strcmp(argv[2], "32") ? 32 : !strcmp(argv[2], "64") ? 64 : 0;
        if (!width || bytes % (width / 8)) return 2;
        const size_t count = bytes / (width / 8), bound = alpn_compress_bound(count, width);
        if (!bound || bound > sizeof out || alpn_compress(in, count, width, ALPN_AUTO, out, bound, &written, NULL) ||
            !written || written > bound || !save("frame", written)) return 3;
        return printf("{\"status\":0,\"written\":%zu}\n", written) < 0 ? 4 : 0;
    }
    if (strcmp(argv[1], "decode") || strlen(argv[2]) != 1 || argv[2][0] < '0' || argv[2][0] > '4') return 2;
    const alpn_backend request = argv[2][0] - '0';
    unsigned width = 0;
    size_t count = 0;
    if (alpn_inspect(in, bytes, &width, &count) || (width != 32 && width != 64) ||
        !count || count > sizeof out / (width / 8)) return 3;
    alpn_decode_stats stats;
    const int status = alpn_decompress_ex(in, bytes, count, out, count, &written, request, &stats);
    const char *error = "";
    if (status == ALPN_INVALID && !strcmp(alpn_last_error(), unavailable)) error = unavailable;
    else if (status != ALPN_OK || written != count || !save("raw", written * (width / 8))) return 3;
    if (printf("{\"status\":%d,\"diagnostic\":\"%s\",\"written\":%zu,\"width\":%u,\"request\":%d,"
               "\"effective\":%d,\"counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"caps\":[",
               status, error, written, width, request, status == ALPN_OK ? stats.effective_backend : -1,
               stats.scalar_vectors, stats.falp_scalar_vectors, stats.falp_avx2_vectors, stats.rd_vectors, stats.raw_vectors) < 0) return 4;
    for (alpn_backend i = 0; i <= ALPN_FALP_SVE; ++i) {
        if (printf("%s[%d,%d]", i ? "," : "", alpn_backend_built(i, width), alpn_backend_available(i, width)) < 0) return 4;
    }
    return puts("]}") < 0 ? 4 : 0;
}
