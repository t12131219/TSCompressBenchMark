#include "tscb_adapter_v1.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    static const size_t sizes[] = {0, 1, 2, 7, 8, 9, 127, 128, 129,
                                    65535, 65536, 65537, 131072};
    for (unsigned pattern = 0; pattern < 3; ++pattern) {
        for (size_t k = 0; k < sizeof(sizes)/sizeof(sizes[0]); ++k) {
            size_t n = sizes[k];
            unsigned char *src = malloc(n + 1), *decoded = malloc(n + 1);
            unsigned char *compressed;
            tscb_codec_handle_v1 *handle = NULL;
            tscb_buffer_v1 in = {0}, out = {0}, unpacked = {0};
            uint64_t bound = 0;
            assert(src && decoded);
            for (size_t i = 0; i < n; ++i) {
                src[i] = pattern == 0 ? 0 : pattern == 1 ? (unsigned char)(i % 5)
                                                      : (unsigned char)((i * 67) ^ (i >> 7));
            }
            assert(tscb_create("{}", 2, &handle) == TSCB_STATUS_OK_V1);
            in.data = src; in.capacity_bytes = in.used_bytes = n;
            in.dtype = TSCB_DTYPE_BYTES_V1; in.rank = 1;
            assert(tscb_compress_bound(handle, &in, &bound) == TSCB_STATUS_OK_V1);
            compressed = malloc((size_t)bound + 1);
            assert(compressed);
            compressed[bound] = 0xA5;
            out.data = compressed; out.capacity_bytes = bound;
            out.dtype = TSCB_DTYPE_BYTES_V1; out.rank = 1;
            assert(tscb_compress(handle, &in, &out) == TSCB_STATUS_OK_V1);
            assert(compressed[bound] == 0xA5 && out.used_bytes <= bound);
            in.data = compressed; in.capacity_bytes = in.used_bytes = out.used_bytes;
            unpacked.data = decoded; unpacked.capacity_bytes = n;
            unpacked.dtype = TSCB_DTYPE_BYTES_V1; unpacked.rank = 1;
            assert(tscb_decompress(handle, &in, &unpacked) == TSCB_STATUS_OK_V1);
            assert(unpacked.used_bytes == n && memcmp(src, decoded, n) == 0);
            assert(tscb_finalize(handle, &out) == TSCB_STATUS_OK_V1);
            assert(out.used_bytes == 0);
            assert(tscb_finalize(handle, &out) != TSCB_STATUS_OK_V1);
            assert(tscb_destroy(handle) == TSCB_STATUS_OK_V1);
            free(src); free(decoded); free(compressed);
        }
    }
    puts("entropy qualification passed");
    return 0;
}
