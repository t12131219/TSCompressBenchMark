#define _POSIX_C_SOURCE 200809L
#include "tscb_adapter_v1.h"
#include <dlfcn.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef uint32_t (*abi_fn)(void);
typedef tscb_status_v1 (*create_fn)(const char *, uint64_t, tscb_codec_handle_v1 **);
typedef tscb_status_v1 (*destroy_fn)(tscb_codec_handle_v1 *);
typedef tscb_status_v1 (*reset_fn)(tscb_codec_handle_v1 *, uint32_t);
typedef tscb_status_v1 (*bound_fn)(tscb_codec_handle_v1 *, const tscb_buffer_v1 *, uint64_t *);
typedef tscb_status_v1 (*transform_fn)(tscb_codec_handle_v1 *, const tscb_buffer_v1 *, tscb_buffer_v1 *);
typedef tscb_status_v1 (*finish_fn)(tscb_codec_handle_v1 *, tscb_buffer_v1 *);
typedef tscb_status_v1 (*error_fn)(tscb_codec_handle_v1 *, const char **, uint64_t *);

static error_fn native_error;

static void require_status(tscb_status_v1 status, tscb_codec_handle_v1 *handle, const char *stage) {
    if (status == TSCB_STATUS_OK_V1) return;
    const char *message = "";
    uint64_t size = 0;
    if (handle && native_error) native_error(handle, &message, &size);
    fprintf(stderr, "%s status=%u: %.*s\n", stage, status, (int)size, message ? message : "");
    exit(2);
}

static void *symbol(void *library, const char *name) {
    void *result = dlsym(library, name);
    if (!result) { fprintf(stderr, "missing symbol %s: %s\n", name, dlerror()); exit(2); }
    return result;
}

static uint64_t clock_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) { perror("clock_gettime"); exit(2); }
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}

static void *allocate(uint64_t bytes) {
    if (bytes > UINT64_C(2147483648)) { fprintf(stderr, "allocation exceeds 2 GiB\n"); exit(2); }
    void *p = malloc(bytes ? (size_t)bytes : 1);
    if (!p) { perror("malloc"); exit(2); }
    return p;
}

static tscb_buffer_v1 buffer(void *data, uint64_t capacity, uint64_t used) {
    tscb_buffer_v1 b = {0};
    b.data = data; b.capacity_bytes = capacity; b.used_bytes = used;
    b.dtype = TSCB_DTYPE_BYTES_V1; b.rank = 1; b.shape[0] = used;
    b.strides_bytes[0] = 1; b.alignment_bytes = 1; b.ownership = TSCB_OWNERSHIP_BORROWED_V1;
    return b;
}

static unsigned char *read_input(const char *path, uint64_t *length) {
    FILE *f = fopen(path, "rb");
    if (!f || fseek(f, 0, SEEK_END)) { perror("read input"); exit(2); }
    long size = ftell(f);
    if (size < 0 || fseek(f, 0, SEEK_SET)) { perror("input size"); exit(2); }
    *length = (uint64_t)size;
    unsigned char *bytes = allocate(*length);
    if (fread(bytes, 1, (size_t)*length, f) != *length || fclose(f)) { fprintf(stderr, "input read failed\n"); exit(2); }
    return bytes;
}

static void write_bytes(const char *path, const void *data, uint64_t length) {
    FILE *f = fopen(path, "wb");
    if (!f || fwrite(data, 1, (size_t)length, f) != length || fclose(f)) { fprintf(stderr, "output write failed\n"); exit(2); }
}

static void write_json_string(const char *text) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", (unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}

static void write_runtime_paths(void) {
    FILE *maps = fopen("/proc/self/maps", "r");
    printf(",\"runtime_maps_available\":%s,\"runtime_mapped_paths\":[", maps ? "true" : "false");
    if (maps) {
        char line[8192];
        char *seen[256];
        size_t count = 0;
        while (fgets(line, sizeof(line), maps)) {
            char *path = strchr(line, '/');
            if (!path || !strstr(path, ".so")) continue;
            path[strcspn(path, "\r\n")] = '\0';
            size_t i = 0;
            while (i < count && strcmp(seen[i], path)) ++i;
            if (i < count) continue;
            if (count == sizeof(seen) / sizeof(seen[0])) { fprintf(stderr, "too many mapped libraries\n"); exit(2); }
            seen[count] = strdup(path);
            if (!seen[count]) { perror("strdup"); exit(2); }
            if (count) putchar(',');
            write_json_string(path);
            ++count;
        }
        fclose(maps);
        for (size_t i = 0; i < count; ++i) free(seen[i]);
    }
    putchar(']');
}

int main(int argc, char **argv) {
    if (argc != 7 || (strcmp(argv[2], "zstd-frame") && strcmp(argv[2], "lzss-raw"))) {
        fprintf(stderr, "usage: reference LIB CODEC INPUT CONFIG_JSON PAYLOAD RESTORED\n"); return 2;
    }
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 2; }
    abi_fn abi = (abi_fn)symbol(library, "tscb_get_abi_version");
    if (abi() != TSCB_ADAPTER_ABI_V1) { fprintf(stderr, "ABI version mismatch\n"); return 2; }
    create_fn create = (create_fn)symbol(library, "tscb_create");
    destroy_fn destroy = (destroy_fn)symbol(library, "tscb_destroy");
    reset_fn reset = (reset_fn)symbol(library, "tscb_reset");
    bound_fn bound = (bound_fn)symbol(library, "tscb_compress_bound");
    transform_fn compress = (transform_fn)symbol(library, "tscb_compress");
    transform_fn decompress = (transform_fn)symbol(library, "tscb_decompress");
    finish_fn finish = (finish_fn)symbol(library, "tscb_finalize");
    native_error = (error_fn)symbol(library, "tscb_get_last_error");
    uint64_t raw_length = 0, bound_length = 0;
    unsigned char *raw = read_input(argv[3], &raw_length);
    uint64_t prepare_begin = clock_ns();
    tscb_buffer_v1 input = buffer(raw, raw_length, raw_length);
    tscb_codec_handle_v1 *encoder = NULL;
    require_status(create(argv[4], strlen(argv[4]), &encoder), encoder, "encode.create");
    if (!encoder) { fprintf(stderr, "null encoder\n"); return 2; }
    require_status(reset(encoder, 0), encoder, "encode.reset");
    require_status(bound(encoder, &input, &bound_length), encoder, "encode.bound");
    unsigned char *compressed_head = allocate(bound_length), *compressed_tail = allocate(bound_length);
    tscb_buffer_v1 encoded = buffer(compressed_head, bound_length, 0);
    tscb_buffer_v1 finalized = buffer(compressed_tail, strcmp(argv[2], "lzss-raw") ? bound_length : 0, 0);
    uint64_t encode_prepare_ns = clock_ns() - prepare_begin;
    uint64_t begin = clock_ns();
    tscb_status_v1 encode_status = compress(encoder, &input, &encoded);
    tscb_status_v1 finish_status = encode_status == TSCB_STATUS_OK_V1 ? finish(encoder, &finalized) : encode_status;
    uint64_t encode_ns = clock_ns() - begin;
    uint64_t postprocess_begin = clock_ns();
    require_status(encode_status, encoder, "encode.compress");
    require_status(finish_status, encoder, "encode.finalize");
    if (encoded.used_bytes > encoded.capacity_bytes || finalized.used_bytes > finalized.capacity_bytes) {
        fprintf(stderr, "native output exceeded capacity\n"); return 2;
    }
    uint64_t stored = encoded.used_bytes + finalized.used_bytes;
    unsigned char *payload = allocate(stored);
    memcpy(payload, compressed_head, (size_t)encoded.used_bytes);
    memcpy(payload + encoded.used_bytes, compressed_tail, (size_t)finalized.used_bytes);
    require_status(destroy(encoder), NULL, "encode.destroy");
    encoder = NULL;
    uint64_t encode_postprocess_ns = clock_ns() - postprocess_begin;
    prepare_begin = clock_ns();
    tscb_codec_handle_v1 *decoder = NULL;
    require_status(create(argv[4], strlen(argv[4]), &decoder), decoder, "decode.create");
    if (!decoder) { fprintf(stderr, "null decoder\n"); return 2; }
    require_status(reset(decoder, 0), decoder, "decode.reset");
    unsigned char *restored = allocate(raw_length);
    tscb_buffer_v1 decode_input = buffer(payload, stored, stored);
    tscb_buffer_v1 decode_output = buffer(restored, raw_length, 0);
    uint64_t decode_prepare_ns = clock_ns() - prepare_begin;
    begin = clock_ns();
    tscb_status_v1 decode_status = decompress(decoder, &decode_input, &decode_output);
    uint64_t decode_ns = clock_ns() - begin;
    postprocess_begin = clock_ns();
    require_status(decode_status, decoder, "decode.decompress");
    if (decode_output.used_bytes != raw_length || memcmp(raw, restored, (size_t)raw_length)) {
        fprintf(stderr, "bitwise recovery mismatch\n"); return 2;
    }
    require_status(destroy(decoder), NULL, "decode.destroy");
    uint64_t decode_postprocess_ns = clock_ns() - postprocess_begin;
    write_bytes(argv[5], payload, stored);
    write_bytes(argv[6], restored, raw_length);
    printf("{\"schema\":\"tsbench.native-crosscheck/1\",\"boundary\":\"native_api_diagnostic\","
           "\"clock\":\"CLOCK_MONOTONIC\",\"raw_bytes\":%" PRIu64 ",\"payload_bytes\":%" PRIu64 ","
           "\"compress_bytes\":%" PRIu64 ",\"finalize_bytes\":%" PRIu64 ",\"bound_bytes\":%" PRIu64 ","
           "\"encode_ns\":%" PRIu64 ",\"decode_ns\":%" PRIu64 ",\"buffer_struct_bytes\":%zu,"
           "\"encode_prepare_ns\":%" PRIu64 ",\"decode_prepare_ns\":%" PRIu64 ","
           "\"encode_postprocess_ns\":%" PRIu64 ",\"decode_postprocess_ns\":%" PRIu64 ","
           "\"buffer_offsets\":[%zu,%zu,%zu,%zu,%zu,%zu,%zu,%zu,%zu,%zu],"
           "\"native_timing_struct_bytes\":%zu,\"native_timing_offsets\":[%zu,%zu,%zu,%zu],\"bitwise_passed\":true",
           raw_length, stored, encoded.used_bytes, finalized.used_bytes, bound_length, encode_ns, decode_ns, sizeof(tscb_buffer_v1),
           encode_prepare_ns, decode_prepare_ns, encode_postprocess_ns, decode_postprocess_ns,
           offsetof(tscb_buffer_v1, data), offsetof(tscb_buffer_v1, capacity_bytes), offsetof(tscb_buffer_v1, used_bytes),
           offsetof(tscb_buffer_v1, dtype), offsetof(tscb_buffer_v1, rank), offsetof(tscb_buffer_v1, shape),
           offsetof(tscb_buffer_v1, strides_bytes), offsetof(tscb_buffer_v1, alignment_bytes), offsetof(tscb_buffer_v1, ownership),
           offsetof(tscb_buffer_v1, reserved), sizeof(tscb_native_timing_v1), offsetof(tscb_native_timing_v1, struct_size),
           offsetof(tscb_native_timing_v1, version), offsetof(tscb_native_timing_v1, native_encode_wall_ns),
           offsetof(tscb_native_timing_v1, native_decode_wall_ns));
    printf(",\"process_pid\":%ld,\"parent_pid\":%ld", (long)getpid(), (long)getppid());
    write_runtime_paths();
    puts("}");
    free(raw); free(compressed_head); free(compressed_tail); free(payload); free(restored);
    dlclose(library);
    return 0;
}
