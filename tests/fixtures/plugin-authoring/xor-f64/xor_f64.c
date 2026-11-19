/* Test-only reversible byte transform for the ABI/manifest authoring regression.
 * No claim of compression. Frame: version, key, u16le schema size, then
 * unchanged schema and XOR'd dense f64 bytes (no dependence on original input). */
#include "tsbench/plugin_abi.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef WIRE_VERSION
#define WIRE_VERSION 1
#endif
struct bmk_context { uint8_t key; const char *operation; };
struct decoded { bmk_array_view column; uint8_t data[]; };

static void drop_blob(bmk_blob *out) { free(out->owner); *out = (bmk_blob){.struct_size = sizeof(*out)}; }
static void drop_object(bmk_owned_object *out) {
    free(out->owner);
    *out = (bmk_owned_object){.struct_size = sizeof(*out)};
}
static void blob(bmk_blob *out, uint8_t *data, size_t n) {
    *out = (bmk_blob){.struct_size = sizeof(*out), .data = data, .size = n,
                      .capacity = n, .owner = data, .release = drop_blob};
}
static bmk_status text(bmk_blob *out, const char *s) {
    size_t n = strlen(s);
    uint8_t *p = malloc(n);
    if (!p) return BMK_NO_MEMORY;
    memcpy(p, s, n);
    blob(out, p, n);
    return BMK_OK;
}
static int supported(const bmk_object_view *input) {
    if (!input || input->struct_size < sizeof(*input) || input->column_count != 1 || !input->columns ||
        input->schema_bytes > 4096 || (input->schema_bytes && !input->schema_json)) return 0;
    const bmk_array_view *col = input->columns;
    return col->struct_size >= sizeof(*col) && col->dtype == BMK_F64 && col->rank == 1 && !col->flags &&
        !col->validity && !col->validity_bytes && !col->validity_bit_offset && col->strides_bytes[0] == 8 &&
        !col->origin_offset && col->shape[0] <= 8192 && col->storage_bytes == col->shape[0] * 8 &&
        (!col->storage_bytes || col->storage);
}
static bmk_status probe(const bmk_object_view *input, const uint8_t *opts, uint64_t n, bmk_blob *out) {
    (void)opts; (void)n;
    return supported(input) ? text(out, "{\"mode\":\"batch\",\"threads\":1}") : BMK_UNSUPPORTED;
}
static int matches(const uint8_t *opts, uint64_t n, const char *s) {
    return opts && n == strlen(s) && !memcmp(opts, s, n);
}
static bmk_status create(const bmk_host_v1 *host, const uint8_t *opts, uint64_t n, bmk_context **out) {
    if (!host || host->abi_version != BMK_ABI_V1 || !out) return BMK_BAD_INPUT;
    *out = NULL;
    uint8_t key = 90;
    if (WIRE_VERSION == 1) {
        if (!matches(opts, n, "{}")) return BMK_BAD_OPTIONS;
    } else {
        if (matches(opts, n, "{\"key\":165}")) key = 165;
        else if (!matches(opts, n, "{\"key\":90}")) return BMK_BAD_OPTIONS;
    }
    *out = malloc(sizeof(**out));
    if (!*out) return BMK_NO_MEMORY;
    **out = (bmk_context){.key = key};
    return BMK_OK;
}
static bmk_status reset(bmk_context *ctx, uint32_t kind) {
    if (kind || !ctx) return BMK_UNSUPPORTED;
    ctx->operation = NULL;
    return BMK_OK;
}
static bmk_status encode(bmk_context *ctx, const bmk_object_view *input, bmk_blob *out) {
    if (!ctx || !out || !supported(input)) return BMK_UNSUPPORTED;
    size_t schema = input->schema_bytes, bytes = input->columns[0].storage_bytes;
    uint8_t *p = malloc(4 + schema + bytes);
    if (!p) return BMK_NO_MEMORY;
    p[0] = WIRE_VERSION; p[1] = ctx->key; p[2] = (uint8_t)schema; p[3] = (uint8_t)(schema >> 8);
    if (schema) memcpy(p + 4, input->schema_json, schema);
    const uint8_t *src = input->columns[0].storage;
    for (size_t i = 0; i < bytes; ++i) p[4 + schema + i] = src[i] ^ ctx->key;
    blob(out, p, 4 + schema + bytes);
    ctx->operation = "encode";
    return BMK_OK;
}
static bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) {
    if (!ctx || !out || !p || n < 4 || p[0] != WIRE_VERSION || (p[1] != 90 && p[1] != 165)) return BMK_CORRUPT;
    size_t schema = (size_t)p[2] + (size_t)p[3] * 256;
    if (schema > 4096 || n < 4 + schema || n - 4 - schema > 8192 * 8 || (n - 4 - schema) % 8) return BMK_CORRUPT;
    size_t bytes = n - 4 - schema;
    struct decoded *mem = malloc(sizeof(*mem) + bytes + schema);
    if (!mem) return BMK_NO_MEMORY;
    memcpy(mem->data + bytes, p + 4, schema);
    for (size_t i = 0; i < bytes; ++i) mem->data[i] = p[4 + schema + i] ^ p[1];
    mem->column = (bmk_array_view){.struct_size = sizeof(mem->column), .dtype = BMK_F64, .rank = 1,
        .storage = mem->data, .storage_bytes = bytes, .shape = {bytes / 8}, .strides_bytes = {8}};
    *out = (bmk_owned_object){.struct_size = sizeof(*out), .owner = mem, .release = drop_object,
        .view = {.struct_size = sizeof(bmk_object_view), .column_count = 1, .columns = &mem->column,
                 .schema_json = mem->data + bytes, .schema_bytes = schema}};
    ctx->operation = "decode";
    return BMK_OK;
}
static bmk_status info(bmk_context *ctx, bmk_blob *out) {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    char json[256];
    snprintf(json, sizeof(json), "{\"operation\":\"%s\",\"mode\":\"batch\",\"backend\":\"test-xor-v%d\","
             "\"threads\":1,\"fallback\":false,\"key\":%u}", ctx->operation, WIRE_VERSION, (unsigned)ctx->key);
    return text(out, json);
}
static bmk_status error(bmk_context *ctx, char *dst, uint64_t n) {
    (void)ctx;
    if (!dst || !n) return BMK_BAD_INPUT;
    snprintf(dst, (size_t)n, "test xor fixture rejected request");
    return BMK_OK;
}
static void destroy(bmk_context *ctx) { free(ctx); }
static const void *extension(const char *name, uint32_t version) { (void)name; (void)version; return NULL; }
static const bmk_plugin_v1 api = {
    .struct_size = sizeof(api), .abi_version = BMK_ABI_V1, .plugin_id = "test-xor-f64", .probe = probe,
    .create = create, .reset = reset, .encode = encode, .decode = decode, .execution_info = info,
    .error_text = error, .destroy = destroy, .extension = extension
};
const bmk_plugin_v1 *bmk_get_plugin(uint32_t abi) { return abi == BMK_ABI_V1 ? &api : NULL; }
