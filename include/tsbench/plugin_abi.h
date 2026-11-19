/* Benchmark plugin ABI v1; ownership and lifetime see design §5.2. */
#ifndef BMK_PLUGIN_ABI_H
#define BMK_PLUGIN_ABI_H
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BMK_ABI_V1 1u
#define BMK_MAX_RANK 8u

typedef int32_t bmk_status;
enum {
    BMK_OK = 0, BMK_UNSUPPORTED = 1, BMK_BAD_INPUT = 2,
    BMK_BAD_OPTIONS = 3, BMK_NO_MEMORY = 4, BMK_CORRUPT = 5,
    BMK_INTERNAL = 6, BMK_RESOURCE_LIMIT = 7
};
enum {
    BMK_I8=1, BMK_U8, BMK_I16, BMK_U16, BMK_I32, BMK_U32,
    BMK_I64, BMK_U64, BMK_F32, BMK_F64, BMK_BOOL, BMK_F16
};

typedef struct {
    uint32_t struct_size, dtype, rank, flags;
    const void *storage;       /* allocation base; borrowed */
    uint64_t storage_bytes, origin_offset;
    uint64_t shape[BMK_MAX_RANK];
    int64_t strides_bytes[BMK_MAX_RANK];
    const uint8_t *validity;   /* NULL means all valid */
    uint64_t validity_bytes, validity_bit_offset;
} bmk_array_view;

typedef struct {
    uint32_t struct_size, column_count;
    const bmk_array_view *columns;
    const uint8_t *schema_json;
    uint64_t schema_bytes;
} bmk_object_view;

typedef struct bmk_blob {
    uint32_t struct_size, flags;
    const uint8_t *data;
    uint64_t size, capacity;
    void *owner;
    void (*release)(struct bmk_blob *self);
} bmk_blob;

typedef struct bmk_owned_object {
    uint32_t struct_size, flags;
    bmk_object_view view;
    void *owner;
    void (*release)(struct bmk_owned_object *self);
} bmk_owned_object;

typedef struct {
    uint32_t struct_size, abi_version;
    void *trace_user;
    /* span IDs are local to a trial; parent=0 denotes a root span. */
    uint64_t (*span_begin)(void *user, const char *stage, uint64_t parent);
    void (*span_end)(void *user, uint64_t span);
    void (*counter_u64)(void *user, const char *name, uint64_t value);
} bmk_host_v1;

typedef struct bmk_context bmk_context;
typedef struct {
    uint32_t struct_size, abi_version;
    const char *plugin_id;     /* valid while module is loaded */
    bmk_status (*probe)(const bmk_object_view *input,
                        const uint8_t *request_json, uint64_t request_bytes,
                        bmk_blob *capability_json);
    bmk_status (*create)(const bmk_host_v1 *host,
                         const uint8_t *options_json, uint64_t options_bytes,
                         bmk_context **out);
    bmk_status (*reset)(bmk_context *ctx, uint32_t reset_kind);
    bmk_status (*encode)(bmk_context *ctx, const bmk_object_view *input,
                         bmk_blob *stream);
    bmk_status (*decode)(bmk_context *ctx, const uint8_t *stream,
                         uint64_t stream_bytes, bmk_owned_object *output);
    bmk_status (*execution_info)(bmk_context *ctx, bmk_blob *json);
    bmk_status (*error_text)(bmk_context *ctx, char *dst, uint64_t capacity);
    void (*destroy)(bmk_context *ctx);
    const void *(*extension)(const char *name, uint32_t version);
} bmk_plugin_v1;

/* The exported entry point returns NULL for an unsupported ABI. */
const bmk_plugin_v1 *bmk_get_plugin(uint32_t requested_abi);

#ifdef __cplusplus
}
#endif
#endif
