// Intentional strong replacements of the weak public source API methods for faults only.
// This executable links the exact shipped shim.o; it is never used for performance.
#include "tscb_adapter_v1.h"
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <initializer_list>
#include <time.h>

static unsigned mode = 0, api_calls = 0, clock_calls = 0;
extern "C" int __wrap_clock_gettime(clockid_t, struct timespec *target) {
    target->tv_sec = 0; target->tv_nsec = ++clock_calls * 100; return 0;
}
extern "C" void marked_encode(void*, const uint32_t*, size_t, uint32_t*, size_t&)
    asm("_ZN11FastPForLib12Simple8b_RLEILb1EE11encodeArrayEPKjmPjRm");
extern "C" void unmarked_encode(void*, const uint32_t*, size_t, uint32_t*, size_t&)
    asm("_ZN11FastPForLib12Simple8b_RLEILb0EE11encodeArrayEPKjmPjRm");
extern "C" const uint32_t* marked_decode(void*, const uint32_t*, size_t, uint32_t*, size_t&)
    asm("_ZN11FastPForLib12Simple8b_RLEILb1EE11decodeArrayEPKjmPjRm");
extern "C" const uint32_t* unmarked_decode(void*, const uint32_t*, size_t, uint32_t*, size_t&)
    asm("_ZN11FastPForLib12Simple8b_RLEILb0EE11decodeArrayEPKjmPjRm");

static void encode_fault(uint32_t *output, size_t& used) {
    ++api_calls;
    if (mode == 1) throw std::logic_error("injected original encode exception");
    if (mode == 2) { used = SIZE_MAX; return; }
    output[0] = 0; used = 1; // Incomplete word / invalid marked count.
}
extern "C" void marked_encode(void*, const uint32_t*, size_t, uint32_t *p, size_t& used) {
    encode_fault(p, used);
}
extern "C" void unmarked_encode(void*, const uint32_t*, size_t, uint32_t *p, size_t& used) {
    encode_fault(p, used);
}
static const uint32_t* decode_fault(const uint32_t *input, size_t length, size_t& count) {
    ++api_calls;
    if (mode == 1) throw std::logic_error("injected original decode exception");
    if (mode == 2) { count = SIZE_MAX; return input + length; }
    return nullptr; // Invalid source consumption, with count unchanged.
}
extern "C" const uint32_t* marked_decode(void*, const uint32_t *p, size_t n, uint32_t*, size_t& count) {
    return decode_fault(p, n, count);
}
extern "C" const uint32_t* unmarked_decode(void*, const uint32_t *p, size_t n, uint32_t*, size_t& count) {
    return decode_fault(p, n, count);
}
static void need(bool valid, const char *message) {
    if (!valid) { std::fprintf(stderr, "%s\n", message); std::exit(2); }
}
static tscb_buffer_v1 descriptor(void *data, uint64_t capacity, uint64_t used, bool integer) {
    tscb_buffer_v1 b{};
    b.data = data; b.capacity_bytes = capacity; b.used_bytes = used;
    b.rank = 1; b.dtype = integer ? TSCB_DTYPE_U32_LE_V1 : TSCB_DTYPE_BYTES_V1;
    b.shape[0] = integer ? capacity / 4 : capacity;
    b.strides_bytes[0] = integer ? 4 : 1; b.alignment_bytes = 1;
    return b;
}
static void put(unsigned char *p, uint64_t value, unsigned bytes) {
    for (unsigned i = 0; i < bytes; ++i) p[i] = static_cast<unsigned char>(value >> (8 * i));
}
int main() {
    unsigned checks = 0;
    for (bool marked : {false,true}) {
        char json[128];
        int size = std::snprintf(json, sizeof(json),
            "{\"codec\":\"SIMPLE8B_RLE\",\"isa\":\"SCALAR\",\"mark_length\":%s}",
            marked ? "true" : "false");
        tscb_codec_handle_v1 *h = nullptr;
        need(tscb_create(json, size, &h) == TSCB_STATUS_OK_V1, "fault create failed");
        need(tscb_set_native_timing(h, 1) == TSCB_STATUS_OK_V1, "fault enable failed");
        unsigned char frame[52]{};
        const size_t frame_size = marked ? 52 : 48;
        std::memcpy(frame, "TSCB8BR1", 8);
        put(frame + 8, 1, 4); put(frame + 16, marked, 4); put(frame + 20, marked ? 3 : 2, 4);
        if (marked) put(frame + 32, 1, 4);
        put(frame + 32 + (marked ? 4 : 0), UINT64_C(0x1000000000000001), 8);
        uint64_t hash = UINT64_C(14695981039346656037);
        for (size_t i = 0; i < frame_size - 8; ++i)
            hash = (hash ^ frame[i]) * UINT64_C(1099511628211);
        put(frame + frame_size - 8, hash, 8);
        for (bool encode : {false,true}) for (mode = 1; mode <= 3; ++mode) {
            need(tscb_reset(h, 0) == TSCB_STATUS_OK_V1, "fault reset failed");
            api_calls = clock_calls = 0;
            uint32_t value = 1;
            unsigned char target[64]; std::memset(target, 0xa5, sizeof(target));
            auto input = encode ? descriptor(&value, 4, 4, true)
                                : descriptor(frame, frame_size, frame_size, false);
            auto output = descriptor(target, encode ? 64 : 4, 0, !encode);
            const auto before = output;
            const auto status = encode ? tscb_compress(h, &input, &output)
                                       : tscb_decompress(h, &input, &output);
            need(status == TSCB_STATUS_CODEC_ERROR_V1 && api_calls == 1 && clock_calls == 2,
                 "source public-API fault not invoked exactly within one timed interval");
            need(std::memcmp(&output, &before, sizeof(output)) == 0,
                 "source fault published output descriptor");
            for (unsigned char byte : target) need(byte == 0xa5, "source fault published bytes");
            tscb_native_timing_v1 time{sizeof(time), 1, 77, 88};
            const auto timed = tscb_get_native_timing(h, &time);
            if (mode == 1)
                need(timed == TSCB_STATUS_UNSUPPORTED_V1 && time.native_encode_wall_ns == 77 &&
                     time.native_decode_wall_ns == 88, "source exception published usable timing");
            else
                need(timed == TSCB_STATUS_OK_V1 &&
                     (encode ? time.native_encode_wall_ns : time.native_decode_wall_ns) == 100,
                     "failed source result did not retain actual API interval");
            ++checks;
        }
        need(tscb_destroy(h) == TSCB_STATUS_OK_V1, "fault destroy failed");
    }
    std::printf("{\"status\":\"PASS\",\"source_fault_checks\":%u,"
                "\"intentional_source_api_replacement\":true,\"same_shipped_object\":true}\n", checks);
}
