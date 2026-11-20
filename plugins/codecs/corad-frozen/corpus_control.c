/* Bounded trusted-input control for the r6 CORAD corpus profile. */
#include "corad.h"
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TRAIN_ROWS 129u
#define MAX_COLUMNS 8u
#define MAX_TEST_ROWS 4096u
#define MODEL_CAP 16384u
#define FRAME_CAP (256u * 1024u)

static uint32_t dimension(const char *s, uint32_t lo, uint32_t hi) {
    char *end;
    errno = 0;
    unsigned long n = strtoul(s, &end, 10);
    if (errno || end == s || *end || *s < '0' || *s > '9' || n < lo || n > hi) exit(2);
    return (uint32_t)n;
}

static size_t read_blob(const char *path, void *data, size_t cap) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    size_t n = fread(data, 1, cap, f);
    int ok = fgetc(f) == EOF && !ferror(f);
    return fclose(f) == 0 && ok ? n : 0;
}

static int save(const char *path, const void *data, size_t n) {
    if (!n) return 0;
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    int ok = fwrite(data, 1, n, f) == n;
    return fclose(f) == 0 && ok;
}

static int report(int status, size_t rows, size_t cols, size_t bytes) {
    printf("{\"native_status\":%d,\"rows\":%zu,\"columns\":%zu,\"output_bytes\":%zu}\n",
           status, rows, cols, bytes);
    return 0;
}

static int fit(const char *path, uint32_t cols) {
    double values[TRAIN_ROWS * MAX_COLUMNS];
    uint8_t wire[MODEL_CAP];
    size_t n = TRAIN_ROWS * cols * sizeof(double);
    if (read_blob(path, values, n) != n) return 3;
    const corad_config cfg = {TRAIN_ROWS, cols, 4, 4, 2, 0.9};
    corad_train_options o;
    corad_train_options_init(&o);
    o.seed = 20261103;
    o.training_columns = (1u << cols) - 1;
    o.max_training_samples = (TRAIN_ROWS / 4) * cols;
    o.max_iter = 6;
    o.solver_max_iter = 4000;
    o.alpha = 0.25;
    o.tolerance = 1e-8;
    o.solver_tolerance = 1e-8;
    o.solver = 0;
    o.normalize = 1;
    corad_train_stats s = {0};
    corad_model *model = NULL;
    int rc = corad_model_train(&cfg, values, &o, &model, &s);
    if (rc != CORAD_OK || !model) {
        corad_model_free(model);
        return rc == CORAD_OK ? 4 : report(rc, cfg.rows, cfg.columns, 0);
    }
    rc = corad_model_save(model, wire, sizeof(wire), &n);
    corad_model_free(model);
    if (rc != CORAD_OK) return report(rc, cfg.rows, cfg.columns, 0);
    if (n > sizeof(wire) || !save("model", wire, n) || !isfinite(s.objective) || !isfinite(s.max_kkt_violation)) return 4;
    printf("{\"native_status\":0,\"rows\":%u,\"columns\":%u,\"output_bytes\":%zu,"
           "\"training_samples\":%zu,\"resampled_atoms\":%zu,\"iterations\":%u,\"converged\":%d,"
           "\"objective\":%.17g,\"max_kkt_violation\":%.17g}\n",
           cfg.rows, cfg.columns, n, s.training_samples, s.resampled_atoms, s.iterations,
           s.converged, s.objective, s.max_kkt_violation);
    return 0;
}

static int pack(const char *path, uint32_t cols) {
    double values[16 + 2 * MAX_COLUMNS];
    uint8_t wire[MODEL_CAP];
    size_t n = (16 + 2 * cols) * sizeof(double);
    if (read_blob(path, values, n) != n) return 3;
    const corad_config cfg = {0, cols, 4, 4, 2, 0.9};
    int rc = corad_model_pack(&cfg, values, values + 16, values + 16 + cols, wire, sizeof(wire), &n);
    if (rc != CORAD_OK) return report(rc, 0, cols, 0);
    if (n > sizeof(wire) || !save("model", wire, n)) return 4;
    return report(rc, 0, cols, n);
}

static int encode(const char *model_path, const char *value_path, uint32_t rows, uint32_t cols) {
    uint8_t model_blob[MODEL_CAP], frame[FRAME_CAP];
    double values[MAX_TEST_ROWS * MAX_COLUMNS];
    size_t model_size = read_blob(model_path, model_blob, sizeof(model_blob));
    size_t value_size = rows * cols * sizeof(double), used = 0;
    if (!model_size || read_blob(value_path, values, value_size) != value_size) return 3;
    corad_model *model = NULL;
    corad_config cfg;
    int rc = corad_model_load(model_blob, model_size, &model);
    if (rc == CORAD_OK) rc = corad_model_config(model, rows, 2, 0.9, &cfg);
    if (rc == CORAD_OK && (cfg.rows != rows || cfg.columns != cols || corad_bound(&cfg) > sizeof(frame))) {
        corad_model_free(model);
        return 3;
    }
    if (rc == CORAD_OK) rc = corad_model_encode(model, &cfg, values, frame, sizeof(frame), &used);
    corad_model_free(model);
    if (rc != CORAD_OK) return report(rc, rows, cols, 0);
    if (used > sizeof(frame) || !save("frame", frame, used)) return 4;
    return report(rc, rows, cols, used);
}

static int decode(const char *path, uint32_t rows, uint32_t cols) {
    uint8_t frame[FRAME_CAP];
    double values[MAX_TEST_ROWS * MAX_COLUMNS];
    size_t n = read_blob(path, frame, sizeof(frame)), used = 0;
    if (!n) return 3;
    corad_config cfg;
    size_t cap = (size_t)rows * cols;
    int rc = corad_decode(frame, n, values, cap, cap, &used, &cfg);
    if (rc != CORAD_OK) return report(rc, rows, cols, 0);
    if (used != cap || cfg.rows != rows || cfg.columns != cols || !save("values", values, used * sizeof(double))) return 4;
    return report(rc, rows, cols, used * sizeof(double));
}

int main(int argc, char **argv) {
    if (argc == 4 && !strcmp(argv[1], "train")) return fit(argv[2], dimension(argv[3], 2, MAX_COLUMNS));
    if (argc == 4 && !strcmp(argv[1], "pack")) return pack(argv[2], dimension(argv[3], 2, MAX_COLUMNS));
    if (argc == 6 && !strcmp(argv[1], "encode"))
        return encode(argv[2], argv[3], dimension(argv[4], 1, MAX_TEST_ROWS), dimension(argv[5], 2, MAX_COLUMNS));
    if (argc == 5 && !strcmp(argv[1], "decode"))
        return decode(argv[2], dimension(argv[3], 1, MAX_TEST_ROWS), dimension(argv[4], 2, MAX_COLUMNS));
    return 2;
}
