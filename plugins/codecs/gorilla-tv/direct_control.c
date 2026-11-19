/* Bit-preserving direct-C control for the frozen Gorilla TV batch domain. */
#include "gorilla.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ROW_LIMIT 512
#define BYTE_LIMIT 16384

typedef union {
    unsigned char wire[BYTE_LIMIT];
    g_sample rows[ROW_LIMIT];
} storage;

static int load(const char *path, void *data, size_t capacity, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    *size = fread(data, 1, capacity, f);
    const int ok = fgetc(f) == EOF && !ferror(f);
    return fclose(f) == 0 && ok;
}

static int save(const char *path, const void *data, size_t size) {
    FILE *f = fopen(path, "wbx");
    if (!f) return 0;
    const int ok = fwrite(data, 1, size, f) == size;
    return fclose(f) == 0 && ok;
}

int gorilla_lifecycle(const char *op);

int main(int argc, char **argv) {
    if (argc==2) return gorilla_lifecycle(argv[1]);
    if (argc != 5) return 2;
    int64_t stamps[ROW_LIMIT];
    uint64_t bits[ROW_LIMIT];
    storage s;
    size_t size = 0, values_size = 0, count;
    if (strcmp(argv[1], "encode") == 0) {
        if (!load(argv[2], stamps, sizeof stamps, &size) ||
            !load(argv[3], bits, sizeof bits, &values_size) || size != values_size || size % sizeof bits[0]) return 3;
        count = size / sizeof bits[0];
        for (size_t i = 0; i < count; i++) s.rows[i] = (g_sample){stamps[i], bits[i]};
        g_buffer b = {0};
        if (g_compress(s.rows, count, &b) != G_OK) return 4;
        const int ok = b.size >= 2 && b.size <= BYTE_LIMIT && save(argv[4], b.data, b.size);
        g_free(b.data);
        if (!ok) return 5;
    } else if (strcmp(argv[1], "decode") == 0) {
        if (!load(argv[2], s.wire, sizeof s.wire, &size) || size < 2) return 3;
        g_array a = {0};
        if (g_decompress(s.wire, size, ROW_LIMIT, &a) != G_OK) return 4;
        count = a.count;
        if (count > ROW_LIMIT) { g_free(a.data); return 4; }
        for (size_t i = 0; i < count; i++) {
            stamps[i] = a.data[i].timestamp;
            bits[i] = a.data[i].bits;
        }
        g_free(a.data);
        if (!save(argv[3], stamps, count * sizeof stamps[0]) || !save(argv[4], bits, count * sizeof bits[0])) return 5;
    } else return 2;
    return printf("{\"rows\":%zu}\n", count) < 0 ? 5 : 0;
}
