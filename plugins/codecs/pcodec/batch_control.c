/* Direct control of the frozen C and Rust entry points; no plugin or ABI framing. */
#include "pcodec_source.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* These are test bounds, not native limits. The largest planned input is 6184 B. */
enum { MAX_INPUT = 8192, MAX_PAYLOAD = MAX_INPUT + 65536 };

static int load(const char *path, void *data, size_t cap, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    *size = fread(data, 1, cap, f);
    const int full = fgetc(f) == EOF && !ferror(f);
    return fclose(f) == 0 && full;
}

static int source_encode_matches(const void *raw, size_t count, int type, pc_config cfg,
                                 const uint8_t *payload, size_t size) {
    pcs_config direct = pcs_default_config();
    direct.level = cfg.level;
    direct.mode = cfg.mode;
    direct.delta = cfg.delta;
    direct.order = 0;
    direct.quant_k = cfg.quant_k;
    direct.int_base = 0;
    direct.float_base = cfg.base;
    direct.max_page_n = cfg.chunk_n;
    direct.enable_8_bit = 1;
    pcs_buffer out = {0};
    const int rc = pcs_compress(raw, count, type, &direct, &out);
    const int match = rc == PC_OK && out.data && out.size == size && memcmp(out.data,payload,size) == 0;
    pcs_buffer_free(out.data,out.size);
    return match;
}

int main(int argc, char **argv) {
    if (argc != 5 && argc != 4) return 2;
    const int source = strcmp(argv[1], "source") == 0;
    if (!source && strcmp(argv[1], "native") != 0) return 2;
    char *end = NULL;
    const long id = strtol(argv[2], &end, 10);
    if (end == argv[2] || *end || id < PC_U32 || id > PC_I8 || !pc_source_backend_available()) return 2;
    const int type = (int)id;
    uint64_t storage[MAX_INPUT / sizeof(uint64_t)];  /* aligned input storage for typed native code */
    const void *raw = storage;
    uint8_t payload[MAX_PAYLOAD];
    size_t bytes, size;
    const size_t width = pc_type_size(type);
    if (!width || !load(argv[3], storage, sizeof(storage), &bytes) || bytes % width) return 3;
    const size_t count = bytes / width;
    pc_config cfg = pc_default_config();
    if (cfg.level != 8 || cfg.mode != -1 || cfg.delta != -1 || cfg.chunk_n != 262144) return 4;
    if (argc == 4) {
        if (source || type != PC_F16 || !bytes) return 2;
        uint8_t *rejected = NULL;
        size_t used = 99;
        const int rc = pc_compress_native(raw,count,type,&cfg,&rejected,&used);
        const int ok = rc == PC_UNSUPPORTED && !rejected && !used;
        pc_free(rejected);
        if (!ok) return 5;
        return printf("{\"native_type\":%d,\"rows\":%zu,\"entry\":\"pc_compress_native\","
                      "\"status\":%d,\"output_bytes\":0,\"output_pointer_null\":true}\n",type,count,rc) < 0 ? 10 : 0;
    }
    if (!load(argv[4], payload, sizeof(payload), &size) || !size) return 3;
    if (source) {
        if (!source_encode_matches(raw,count,type,cfg,payload,size)) return 6;
    } else {
        uint8_t *native = NULL;
        size_t used = 0;
        const int rc = pc_compress_native(raw,count,type,&cfg,&native,&used);
        const int match = rc == PC_OK && native && used == size && memcmp(native,payload,size) == 0;
        pc_free(native);
        if (!match) return 6;
    }
    pcs_buffer restored = {0};
    size_t n = 0;
    const int rc = pcs_decompress(payload,size,type,count,&restored,&n);
    const int match = rc == PC_OK && n == count && restored.size == bytes &&
                      (!bytes || (restored.data && memcmp(restored.data,raw,bytes) == 0));
    pcs_buffer_free(restored.data,restored.size);
    if (!match) return 7;
    if (count) {
        void *output = NULL;
        n = 99;
        const int limit = pc_decompress_bounded(payload,size,type,count-1,&output,&n);
        const int denied = limit == PC_LIMIT && !output && !n;
        pc_free(output);
        if (!denied) return 8;
    }
    return printf("{\"native_type\":%d,\"rows\":%zu,\"payload_bytes\":%zu,\"direct_encode\":\"%s\","
                  "\"direct_decode\":\"pcs_decompress\",\"native_output_count_limit_status\":%s}\n",type,count,size,
                  source ? "pcs_compress" : "pc_compress_native",count ? "6" : "null") < 0 ? 10 : 0;
}
