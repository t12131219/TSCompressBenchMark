#include "tsbench/plugin_abi.h"

#include <stdlib.h>
#include <string.h>

/* Persistent format: magic[8], dtype[u32 LE], count[u64 LE], schema_size[u32 LE],
 * opaque schema bytes, densely packed little-endian values. Bit-preserving,
 * including NaNs and signed zero. This baseline does not claim a checksum. */
enum { HEADER_BYTES = 24, MAX_SCHEMA = 65536 };
static const uint8_t magic[8] = {'B','M','K','R','A','W',1,0};
static const uint64_t max_data = UINT64_C(64) * 1024 * 1024;

struct bmk_context { bmk_status last; const char *operation; };
struct decoded { bmk_array_view col; uint8_t bytes[]; };

static size_t width(uint32_t dtype) {
    switch (dtype) {
    case BMK_I8: case BMK_U8: case BMK_BOOL: return 1;
    case BMK_I16: case BMK_U16: case BMK_F16: return 2;
    case BMK_I32: case BMK_U32: case BMK_F32: return 4;
    case BMK_I64: case BMK_U64: case BMK_F64: return 8;
    default: return 0;
    }
}
static void write_le(uint8_t *p, size_t n, uint64_t value) {
    for (size_t i = 0; i < n; ++i) p[i] = (uint8_t)(value >> (8u*i));
}
static uint64_t read_le(const uint8_t *p, size_t n) {
    uint64_t value = 0;
    for (size_t i = 0; i < n; ++i) value |= (uint64_t)p[i] << (8u*i);
    return value;
}
static int is_little_endian(void) {
    const uint16_t one = 1;
    return *(const uint8_t *)&one == 1;
}
static int empty_json(const uint8_t *s, uint64_t n) {
    if (!s || n < 2 || n > 65536) return 0;
    const char *tokens = "{}";
    for (uint64_t i = 0; i < n; ++i) {
        if (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n') continue;
        if (*tokens == '\0' || s[i] != (uint8_t)*tokens++) return 0;
    }
    return *tokens == '\0';
}
static bmk_status validate(const bmk_object_view *input, uint64_t *bytes) {
    if (!input || input->struct_size < sizeof(*input)) return BMK_BAD_INPUT;
    if (input->column_count != 1) return BMK_UNSUPPORTED;
    const bmk_array_view *x = input->columns;
    if (!x || x->struct_size < sizeof(*x)) return BMK_BAD_INPUT;
    const size_t item = width(x->dtype);
    if (!item || x->rank != 1 || x->flags || x->validity || x->validity_bytes || x->validity_bit_offset ||
        x->strides_bytes[0] != (int64_t)item || !is_little_endian()) return BMK_UNSUPPORTED;
    if (x->shape[0] > max_data / item || input->schema_bytes > MAX_SCHEMA) return BMK_RESOURCE_LIMIT;
    *bytes = x->shape[0] * item;
    if (x->origin_offset > x->storage_bytes || *bytes > x->storage_bytes - x->origin_offset ||
        x->origin_offset > SIZE_MAX - *bytes || (*bytes && !x->storage) ||
        (input->schema_bytes && !input->schema_json)) return BMK_BAD_INPUT;
    return BMK_OK;
}
static void release_blob(bmk_blob *b) {
    free(b->owner);
    memset(b, 0, sizeof(*b));
    b->struct_size = sizeof(*b);
}
static int valid_blob(const bmk_blob *out) {
    return out && out->struct_size >= sizeof(*out) && !out->release && !out->owner;
}
static void assign_blob(bmk_blob *out, uint8_t *ptr, size_t len) {
    out->data = ptr; out->size = len; out->capacity = len; out->owner = ptr; out->release = release_blob;
}
static bmk_status text_blob(bmk_blob *out, const char *text) {
    if (!valid_blob(out)) return BMK_BAD_INPUT;
    const size_t n = strlen(text);
    uint8_t *p = malloc(n);
    if (!p) return BMK_NO_MEMORY;
    memcpy(p, text, n);
    assign_blob(out, p, n);
    return BMK_OK;
}
static bmk_status probe(const bmk_object_view *input, const uint8_t *request, uint64_t n, bmk_blob *out) {
    if (!empty_json(request, n)) return BMK_BAD_OPTIONS;
    uint64_t bytes;
    const bmk_status rc = validate(input, &bytes);
    if (rc != BMK_OK) return rc;
    return text_blob(out, "{\"mode\":\"batch\",\"rank\":1,\"threads\":1,\"validity\":false}");
}
static bmk_status create(const bmk_host_v1 *host, const uint8_t *options, uint64_t n, bmk_context **out) {
    if (!out) return BMK_BAD_INPUT;
    *out = NULL;
    if (!host || host->struct_size < sizeof(*host) || host->abi_version != BMK_ABI_V1) return BMK_BAD_INPUT;
    if (!empty_json(options, n)) return BMK_BAD_OPTIONS;
    if (!is_little_endian()) return BMK_UNSUPPORTED;
    *out = calloc(1, sizeof(**out));
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
static bmk_status mark(bmk_context *ctx, bmk_status rc) { if (ctx) ctx->last = rc; return rc; }
static bmk_status reset(bmk_context *ctx, uint32_t kind) {
    if (!ctx || kind != 0) return mark(ctx, BMK_UNSUPPORTED);
    ctx->operation = NULL;
    return mark(ctx, BMK_OK);
}
static bmk_status encode(bmk_context *ctx, const bmk_object_view *input, bmk_blob *out) {
    if (ctx) ctx->operation = NULL;
    if (!ctx || !valid_blob(out)) return mark(ctx, BMK_BAD_INPUT);
    uint64_t bytes;
    bmk_status rc = validate(input, &bytes);
    if (rc != BMK_OK) return mark(ctx, rc);
    const size_t n = HEADER_BYTES + (size_t)input->schema_bytes + (size_t)bytes;
    const bmk_array_view *x = input->columns;
    uint8_t *p = malloc(n);
    if (!p) return mark(ctx, BMK_NO_MEMORY);
    memcpy(p, magic, sizeof(magic));
    write_le(p + 8, 4, x->dtype);
    write_le(p + 12, 8, x->shape[0]);
    write_le(p + 20, 4, input->schema_bytes);
    if (input->schema_bytes) memcpy(p + HEADER_BYTES, input->schema_json, (size_t)input->schema_bytes);
    if (bytes) memcpy(p + HEADER_BYTES + input->schema_bytes, (const uint8_t *)x->storage + x->origin_offset, (size_t)bytes);
    assign_blob(out, p, n);
    ctx->operation = "encode";
    return mark(ctx, BMK_OK);
}
static void release_object(bmk_owned_object *out) {
    free(out->owner);
    memset(out, 0, sizeof(*out));
    out->struct_size = sizeof(*out);
}
static bmk_status decode(bmk_context *ctx, const uint8_t *p, uint64_t n, bmk_owned_object *out) {
    if (ctx) ctx->operation = NULL;
    if (!ctx || !out || out->struct_size < sizeof(*out) || out->release || out->owner) return mark(ctx, BMK_BAD_INPUT);
    if (!p || n < HEADER_BYTES || memcmp(p, magic, sizeof(magic))) return mark(ctx, BMK_CORRUPT);
    const uint32_t dtype = (uint32_t)read_le(p + 8, 4);
    const uint64_t count = read_le(p + 12, 8), schema = read_le(p + 20, 4);
    const size_t item = width(dtype);
    if (!item) return mark(ctx, BMK_CORRUPT);
    if (count > max_data / item || schema > MAX_SCHEMA) return mark(ctx, BMK_RESOURCE_LIMIT);
    const uint64_t data = count * item;
    if (n != HEADER_BYTES + schema + data) return mark(ctx, BMK_CORRUPT);
    struct decoded *o = calloc(1, sizeof(*o) + (size_t)data + (size_t)schema);
    if (!o) return mark(ctx, BMK_NO_MEMORY);
    if (data) memcpy(o->bytes, p + HEADER_BYTES + schema, (size_t)data);
    if (schema) memcpy(o->bytes + data, p + HEADER_BYTES, (size_t)schema);
    o->col.struct_size = sizeof(o->col); o->col.dtype = dtype; o->col.rank = 1;
    o->col.storage = data ? o->bytes : NULL; o->col.storage_bytes = data;
    o->col.shape[0] = count; o->col.strides_bytes[0] = (int64_t)item;
    out->view = (bmk_object_view){ sizeof(out->view), 1, &o->col, schema ? o->bytes + data : NULL, schema };
    out->owner = o; out->release = release_object;
    ctx->operation = "decode";
    return mark(ctx, BMK_OK);
}
static bmk_status execution_info(bmk_context *ctx, bmk_blob *out) {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    return text_blob(out, ctx->operation[0] == 'e' ?
        "{\"backend\":\"copy\",\"mode\":\"batch\",\"threads\":1,\"fallback\":false,\"blocks\":1,\"operation\":\"encode\"}" :
        "{\"backend\":\"copy\",\"mode\":\"batch\",\"threads\":1,\"fallback\":false,\"blocks\":1,\"operation\":\"decode\"}");
}
static bmk_status error_text(bmk_context *ctx, char *dst, uint64_t capacity) {
    static const char *const labels[] = {"", "unsupported view or reset", "invalid input", "invalid options",
        "allocation failed", "malformed raw-store frame", "internal error", "raw-store frame exceeds limits"};
    if (!ctx || !dst || capacity == 0) return BMK_BAD_INPUT;
    const char *s = labels[ctx->last];
    size_t n = strlen(s);
    if ((uint64_t)n >= capacity) n = (size_t)capacity - 1;
    memcpy(dst, s, n); dst[n] = '\0';
    return BMK_OK;
}
static void destroy(bmk_context *ctx) { free(ctx); }
static const void *extension(const char *name, uint32_t version) { (void)name; (void)version; return NULL; }

static const bmk_plugin_v1 plugin = { sizeof(plugin), BMK_ABI_V1, "raw-store", probe, create, reset,
    encode, decode, execution_info, error_text, destroy, extension };

__attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t abi) { return abi == BMK_ABI_V1 ? &plugin : NULL; }
