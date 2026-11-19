/* Direct native CRD1 control: model and input are the only read-only mounts. */
#include "corad.h"
#include <stdint.h>
#include <stdio.h>

static int read_blob(const char *path, void *data, size_t limit, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    *size = fread(data, 1, limit, f);
    int ok = fgetc(f) == EOF && !ferror(f);
    return fclose(f) == 0 && ok;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    uint8_t model_bytes[16384], frame[16384];
    double source[16384 / sizeof(double)];
    size_t n_model, n_source, n_frame = 0;
    corad_model *model = NULL;
    corad_config frozen, effective;
    if (!read_blob(argv[1], model_bytes, sizeof(model_bytes), &n_model) ||
        !read_blob(argv[2], source, sizeof(source), &n_source) ||
        corad_model_load(model_bytes, n_model, &model) != CORAD_OK) return 3;
    int ok = corad_model_info(model, &frozen) == CORAD_OK && frozen.columns > 0 &&
             n_source % (sizeof(double) * frozen.columns) == 0 &&
             corad_model_config(model, (uint32_t)(n_source / (sizeof(double) * frozen.columns)),
                                frozen.nonzero, frozen.threshold, &effective) == CORAD_OK &&
             corad_bound(&effective) <= sizeof(frame) &&
             corad_model_encode(model, &effective, source, frame, sizeof(frame), &n_frame) == CORAD_OK &&
             n_frame && n_frame <= sizeof(frame);
    corad_model_free(model);
    if (!ok) return 4;
    FILE *f = fopen("native", "wb");
    if (!f) return 5;
    ok = fwrite(frame, 1, n_frame, f) == n_frame;
    return fclose(f) == 0 && ok ? 0 : 5;
}
