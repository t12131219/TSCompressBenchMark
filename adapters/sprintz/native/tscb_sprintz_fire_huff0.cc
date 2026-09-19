#include "tscb_native_timing.h"
#include "huf.h"

#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

extern "C" {
int tscb_sprintz_bound(const uint8_t*, size_t, size_t*);
int tscb_sprintz_compress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
int tscb_sprintz_decompress(unsigned, const uint8_t*, size_t, uint8_t*, size_t, size_t*);
}

namespace {
constexpr size_t kSprintzEnvelopeBytes = 16;
constexpr size_t kPipelineHeaderBytes = 32;
constexpr size_t kMaxRawBytes = 120 * 1024;
constexpr uint8_t kPipelineMagic[4] = {'T', 'S', 'H', '1'};
constexpr uint8_t kSprintzFrameMagic[4] = {'T', 'S', 'F', '1'};
constexpr char kConfig[] = "{\"algorithm\":\"sprintz-fire-huff0\"}";
constexpr char kManifest[] =
    "{\"abi_version\":1,\"algorithm\":\"sprintz-fire-huff0\","
    "\"isa\":\"AVX2_BMI2_LZCNT\",\"threading\":\"SINGLE_THREAD\","
    "\"format\":\"SPRINTZ_XFF_RLE_THEN_HUFF0_8B_OR_16B_NDIMS_1_TO_128\"}";

uint16_t read16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0]) |
        static_cast<uint16_t>(static_cast<uint16_t>(p[1]) << 8);
}

uint64_t read64(const uint8_t* p) {
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<uint64_t>(p[i]) << (8 * i);
    return value;
}

void write16(uint8_t* p, uint16_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

void write64(uint8_t* p, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<uint8_t>(value >> (8 * i));
}

bool checked_add(size_t a, size_t b, size_t* result) {
    if (a > std::numeric_limits<size_t>::max() - b) return false;
    *result = a + b;
    return true;
}

bool checked_mul(size_t a, size_t b, size_t* result) {
    if (a && b > std::numeric_limits<size_t>::max() / a) return false;
    *result = a * b;
    return true;
}

bool valid_buffer(const tscb_buffer_v1* buffer) {
    return buffer && buffer->dtype == TSCB_DTYPE_BYTES_V1 && buffer->rank == 1 &&
        buffer->used_bytes <= buffer->capacity_bytes &&
        (buffer->capacity_bytes == 0 || buffer->data);
}

bool overlaps(const tscb_buffer_v1* input, const tscb_buffer_v1* output) {
    const uintptr_t a = reinterpret_cast<uintptr_t>(input->data);
    const uintptr_t b = reinterpret_cast<uintptr_t>(output->data);
    return input->used_bytes && output->capacity_bytes &&
        (a <= b ? b - a < input->used_bytes : a - b < output->capacity_bytes);
}

void set_error(tscb_codec_handle_v1* handle, const char* message);
}  // namespace

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer;
    uint64_t input_bytes;
    uint64_t sprintz_bytes;
    uint64_t stream_bytes;
    bool updated;
    bool finalized;
    char last_error[192];
    char accounting_json[256];
};

namespace {
void set_error(tscb_codec_handle_v1* handle, const char* message) {
    if (handle) std::snprintf(handle->last_error, sizeof(handle->last_error), "%s", message);
}
}  // namespace

extern "C" {

TSCB_NATIVE_TIMING_API

uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }

tscb_status_v1 tscb_get_manifest_json(const char** json, uint64_t* length) {
    if (!json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = kManifest;
    *length = sizeof(kManifest) - 1;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_create(const char* config_json, uint64_t config_length,
                           tscb_codec_handle_v1** handle) {
    if (!config_json || !handle || config_length != sizeof(kConfig) - 1 ||
        std::memcmp(config_json, kConfig, sizeof(kConfig) - 1))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *handle = nullptr;
#if defined(__x86_64__)
    __builtin_cpu_init();
    if (!__builtin_cpu_supports("avx2") || !__builtin_cpu_supports("bmi2") ||
        !__builtin_cpu_supports("lzcnt")) return TSCB_STATUS_UNSUPPORTED_V1;
#else
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    try {
        *handle = new tscb_codec_handle_v1{};
        return TSCB_STATUS_OK_V1;
    } catch (const std::bad_alloc&) { return TSCB_STATUS_CODEC_ERROR_V1; }
}

tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* handle) {
    delete handle;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_reset(tscb_codec_handle_v1* handle, uint32_t reset_mode) {
    if (!handle || reset_mode != 0) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const int enabled = handle->native_timer.enabled;
    *handle = tscb_codec_handle_v1{};
    return tscb_set_native_timing(handle, enabled ? 1u : 0u);
}

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* handle,
                                   const tscb_buffer_v1* input, uint64_t* bound_bytes) {
    if (!handle || !valid_buffer(input) || !bound_bytes ||
        input->used_bytes < kSprintzEnvelopeBytes)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (input->used_bytes - kSprintzEnvelopeBytes > kMaxRawBytes) {
        set_error(handle, "SprintzFIRE+Huf input exceeds the registered Huff0 block limit");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    size_t sprintz_bound = 0;
    if (tscb_sprintz_bound(static_cast<const uint8_t*>(input->data),
                           static_cast<size_t>(input->used_bytes), &sprintz_bound)) {
        set_error(handle, "invalid Sprintz width, dimensions, element count, or envelope");
        return TSCB_STATUS_UNSUPPORTED_V1;
    }
    const size_t huff_bound = HUF_compressBound(HUF_BLOCKSIZE_MAX);
    size_t bound = sprintz_bound > huff_bound ? sprintz_bound : huff_bound;
    if (!checked_add(bound, kPipelineHeaderBytes, &bound))
        return TSCB_STATUS_UNSUPPORTED_V1;
    *bound_bytes = bound;
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_compress(tscb_codec_handle_v1* handle,
                             const tscb_buffer_v1* input, tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(input) || !valid_buffer(output) || handle->updated ||
        handle->finalized || overlaps(input, output))
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    uint64_t bound = 0;
    const auto bound_status = tscb_compress_bound(handle, input, &bound);
    if (bound_status != TSCB_STATUS_OK_V1) return bound_status;
    if (output->capacity_bytes < bound) return TSCB_STATUS_DST_TOO_SMALL_V1;
    try {
        size_t sprintz_bound = 0;
        if (tscb_sprintz_bound(static_cast<const uint8_t*>(input->data),
                               static_cast<size_t>(input->used_bytes), &sprintz_bound))
            return TSCB_STATUS_CODEC_ERROR_V1;
        std::vector<uint8_t> sprintz(sprintz_bound + 32);
        std::vector<uint8_t> huff(HUF_compressBound(HUF_BLOCKSIZE_MAX));
        size_t sprintz_used = 0;
        int sprintz_status = 0;
        size_t huff_result = 0;
        TSCB_TIME_CODEC(handle->native_timer, encode_ns, {
            sprintz_status = tscb_sprintz_compress(
                1, static_cast<const uint8_t*>(input->data),
                static_cast<size_t>(input->used_bytes), sprintz.data(), sprintz_bound,
                &sprintz_used);
            if (!sprintz_status && sprintz_used >= kSprintzEnvelopeBytes) {
                const size_t native_bytes = sprintz_used - kSprintzEnvelopeBytes;
                if (native_bytes <= HUF_BLOCKSIZE_MAX && native_bytes >= 2) {
                    huff_result = HUF_compress(
                        huff.data(), huff.size(),
                        sprintz.data() + kSprintzEnvelopeBytes, native_bytes);
                }
            }
        });
        if (sprintz_status || sprintz_used < kSprintzEnvelopeBytes) {
            set_error(handle, "bounded Sprintz FIRE encoder failed");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
        const size_t native_bytes = sprintz_used - kSprintzEnvelopeBytes;
        if (native_bytes > HUF_BLOCKSIZE_MAX || HUF_isError(huff_result)) {
            set_error(handle, "Huff0 source limit or encoder failure");
            return TSCB_STATUS_CODEC_ERROR_V1;
        }
        auto* destination = static_cast<uint8_t*>(output->data);
        std::memcpy(destination, kPipelineMagic, 4);
        destination[4] = sprintz[4];
        destination[5] = 0;
        write16(destination + 6, read16(sprintz.data() + 6));
        write64(destination + 8, read64(sprintz.data() + 8));
        write64(destination + 16, native_bytes);
        size_t payload_bytes = native_bytes;
        if (huff_result > 1 && huff_result < native_bytes) {
            destination[5] = 1;
            payload_bytes = huff_result;
            std::memcpy(destination + kPipelineHeaderBytes, huff.data(), payload_bytes);
        } else if (huff_result == 1 && native_bytes) {
            destination[5] = 2;
            destination[kPipelineHeaderBytes] = sprintz[kSprintzEnvelopeBytes];
            payload_bytes = 1;
        } else if (native_bytes) {
            std::memcpy(destination + kPipelineHeaderBytes,
                        sprintz.data() + kSprintzEnvelopeBytes, native_bytes);
        }
        write64(destination + 24, payload_bytes);
        output->used_bytes = kPipelineHeaderBytes + payload_bytes;
        handle->input_bytes = input->used_bytes - kSprintzEnvelopeBytes;
        handle->sprintz_bytes = native_bytes;
        handle->stream_bytes = output->used_bytes;
        handle->updated = true;
        return TSCB_STATUS_OK_V1;
    } catch (const std::bad_alloc&) {
        set_error(handle, "SprintzFIRE+Huf allocation failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* handle, tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!handle->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (handle->finalized) return TSCB_STATUS_CODEC_ERROR_V1;
    output->used_bytes = 0;
    handle->finalized = true;
    std::snprintf(handle->accounting_json, sizeof(handle->accounting_json),
                  "{\"input_bytes\":%" PRIu64 ",\"sprintz_native_bytes\":%" PRIu64
                  ",\"pipeline_stream_bytes\":%" PRIu64
                  ",\"pipeline_header_bytes\":32,\"finalize_calls\":1}",
                  handle->input_bytes, handle->sprintz_bytes, handle->stream_bytes);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* handle,
                               const tscb_buffer_v1* input, tscb_buffer_v1* output) {
    if (!handle || !valid_buffer(input) || !valid_buffer(output) ||
        overlaps(input, output) || input->used_bytes < kPipelineHeaderBytes)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const auto* source = static_cast<const uint8_t*>(input->data);
    if (std::memcmp(source, kPipelineMagic, 4) ||
        (source[4] != 1 && source[4] != 2) || source[5] > 2) {
        set_error(handle, "invalid SprintzFIRE+Huf frame header");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    const uint16_t dimensions = read16(source + 6);
    const uint64_t elements64 = read64(source + 8);
    const uint64_t native64 = read64(source + 16);
    const uint64_t payload64 = read64(source + 24);
    size_t raw_bytes = 0;
    if (!dimensions || dimensions > 128 || elements64 % dimensions ||
        elements64 > std::numeric_limits<size_t>::max() ||
        native64 < 8 || native64 > HUF_BLOCKSIZE_MAX ||
        payload64 > std::numeric_limits<size_t>::max() ||
        !checked_mul(static_cast<size_t>(elements64), source[4], &raw_bytes) ||
        raw_bytes > kMaxRawBytes || output->capacity_bytes < raw_bytes) {
        set_error(handle, "invalid SprintzFIRE+Huf shape or declared length");
        return output->capacity_bytes < raw_bytes ? TSCB_STATUS_DST_TOO_SMALL_V1
                                                  : TSCB_STATUS_CODEC_ERROR_V1;
    }
    const size_t native_bytes = static_cast<size_t>(native64);
    const size_t payload_bytes = static_cast<size_t>(input->used_bytes) - kPipelineHeaderBytes;
    const size_t declared_payload_bytes = static_cast<size_t>(payload64);
    if (payload_bytes != declared_payload_bytes ||
        (source[5] == 0 && declared_payload_bytes != native_bytes) ||
        (source[5] == 1 && declared_payload_bytes < 2) ||
        (source[5] == 2 && declared_payload_bytes != 1)) {
        set_error(handle, "invalid Huff0 mode or payload length");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
    try {
        std::vector<uint8_t> native(native_bytes + 32);
        std::vector<uint8_t> sprintz(kSprintzEnvelopeBytes + native_bytes + 32);
        size_t decoded_huff = native_bytes;
        int sprintz_status = 0;
        size_t used = 0;
        TSCB_TIME_CODEC(handle->native_timer, decode_ns, {
            if (source[5] == 0) {
                std::memcpy(native.data(), source + kPipelineHeaderBytes, native_bytes);
            } else if (source[5] == 2) {
                std::memset(native.data(), source[kPipelineHeaderBytes], native_bytes);
            } else {
                decoded_huff = HUF_decompress(native.data(), native_bytes,
                    source + kPipelineHeaderBytes, payload_bytes);
            }
            if (!HUF_isError(decoded_huff) && decoded_huff == native_bytes) {
                std::memcpy(sprintz.data(), kSprintzFrameMagic, 4);
                sprintz[4] = source[4];
                sprintz[5] = 0;
                write16(sprintz.data() + 6, dimensions);
                write64(sprintz.data() + 8, elements64);
                std::memcpy(sprintz.data() + kSprintzEnvelopeBytes,
                            native.data(), native_bytes);
                sprintz_status = tscb_sprintz_decompress(
                    1, sprintz.data(), kSprintzEnvelopeBytes + native_bytes,
                    static_cast<uint8_t*>(output->data),
                    static_cast<size_t>(output->capacity_bytes), &used);
            } else {
                sprintz_status = 4;
            }
        });
        if (sprintz_status || used != raw_bytes) {
            set_error(handle, "Huff0 or bounded Sprintz FIRE decoder rejected the stream");
            return sprintz_status == 2 ? TSCB_STATUS_DST_TOO_SMALL_V1
                                       : TSCB_STATUS_CODEC_ERROR_V1;
        }
        output->used_bytes = used;
        return TSCB_STATUS_OK_V1;
    } catch (const std::bad_alloc&) {
        set_error(handle, "SprintzFIRE+Huf allocation failed");
        return TSCB_STATUS_CODEC_ERROR_V1;
    }
}

tscb_status_v1 tscb_query(tscb_codec_handle_v1* handle, const char*, uint64_t,
                          char*, uint64_t, uint64_t* used) {
    if (used) *used = 0;
    set_error(handle, "SprintzFIRE+Huf does not support random access");
    return TSCB_STATUS_UNSUPPORTED_V1;
}

tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* handle,
                                        const char** json, uint64_t* length) {
    if (!handle || !json || !length || !handle->finalized)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = handle->accounting_json;
    *length = std::strlen(*json);
    return TSCB_STATUS_OK_V1;
}

tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* handle,
                                   const char** message, uint64_t* length) {
    if (!handle || !message || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message = handle->last_error;
    *length = std::strlen(*message);
    return TSCB_STATUS_OK_V1;
}
}
