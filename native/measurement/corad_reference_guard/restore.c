/* Decode one bounded CRD1 frame using the unmodified Unique decoder. */
#include "corad.h"
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    uint8_t frame[16384];
    double output[2048];
    corad_config cfg;
    size_t count = 0;
    FILE *in = fopen(argv[1], "rb");
    if (!in) return 3;
    const size_t size = fread(frame, 1, sizeof(frame), in);
    const int complete = fgetc(in) == EOF && !ferror(in);
    if (fclose(in) || !complete ||
        corad_decode(frame, size, output, 2048, 2048, &count, &cfg) != CORAD_OK ||
        count != (size_t)cfg.rows * cfg.columns) return 4;
    FILE *out = fopen("restored", "wb");
    if (!out) return 5;
    const int ok = fwrite(output, sizeof(*output), count, out) == count;
    return fclose(out) == 0 && ok ? 0 : 5;
}
