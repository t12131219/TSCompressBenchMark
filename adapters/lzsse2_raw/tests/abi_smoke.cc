#include "tscb_adapter_v1.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static tscb_buffer_v1 buffer(void* data, uint64_t capacity, uint64_t used) {
    tscb_buffer_v1 result{};
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.shape[0] = used;
    result.strides_bytes[0] = 1;
    result.alignment_bytes = 1;
    result.ownership = TSCB_OWNERSHIP_CALLER_V1;
    return result;
}

static int round_trip(size_t size) {
    static const char config[] =
        "{\"compression_level\":1,\"content_checksum\":false}";
    tscb_codec_handle_v1* encode = nullptr;
    tscb_codec_handle_v1* decode = nullptr;
    auto* source = static_cast<unsigned char*>(std::malloc(size == 0 ? 1 : size));
    auto* reconstructed = static_cast<unsigned char*>(std::malloc(size == 0 ? 1 : size));
    unsigned char* compressed = nullptr;
    uint64_t bound = 0;
    int result = 1;
    if (source == nullptr || reconstructed == nullptr) goto cleanup;
    for (size_t index = 0; index < size; ++index) {
        source[index] = static_cast<unsigned char>((index * 131U + size) & 0xFFU);
    }
    if (tscb_create(config, sizeof(config) - 1U, &encode) != TSCB_STATUS_OK_V1
        || tscb_create(config, sizeof(config) - 1U, &decode) != TSCB_STATUS_OK_V1) goto cleanup;
    {
        tscb_buffer_v1 input = buffer(source, size, size);
        if (tscb_compress_bound(encode, &input, &bound) != TSCB_STATUS_OK_V1 || bound == 0) {
            goto cleanup;
        }
        compressed = static_cast<unsigned char*>(std::malloc(bound));
        if (compressed == nullptr) goto cleanup;
        tscb_buffer_v1 too_small = buffer(compressed, bound - 1U, 0);
        if (tscb_compress(encode, &input, &too_small) != TSCB_STATUS_DST_TOO_SMALL_V1) {
            goto cleanup;
        }
        tscb_buffer_v1 output = buffer(compressed, bound, 0);
        if (tscb_compress(encode, &input, &output) != TSCB_STATUS_OK_V1) goto cleanup;
        tscb_buffer_v1 final_output = buffer(compressed + output.used_bytes, 0, 0);
        if (tscb_finalize(encode, &final_output) != TSCB_STATUS_OK_V1
            || final_output.used_bytes != 0
            || tscb_finalize(encode, &final_output) == TSCB_STATUS_OK_V1) goto cleanup;
        tscb_buffer_v1 compressed_input = buffer(compressed, output.used_bytes, output.used_bytes);
        tscb_buffer_v1 decoded_output = buffer(reconstructed, size, 0);
        if (tscb_decompress(decode, &compressed_input, &decoded_output) != TSCB_STATUS_OK_V1
            || decoded_output.used_bytes != size
            || std::memcmp(source, reconstructed, size) != 0) goto cleanup;
    }
    result = 0;
cleanup:
    tscb_destroy(encode);
    tscb_destroy(decode);
    std::free(source);
    std::free(compressed);
    std::free(reconstructed);
    return result;
}

int main() {
    if (tscb_get_abi_version() != TSCB_ADAPTER_ABI_V1
        || round_trip(0) || round_trip(1) || round_trip(2)
        || round_trip(65535) || round_trip(65536) || round_trip(65537)
        || round_trip(131073)) {
        std::fputs("Snappy raw C ABI smoke failed\n", stderr);
        return 1;
    }
    std::puts("Snappy raw C ABI smoke passed");
    return 0;
}
