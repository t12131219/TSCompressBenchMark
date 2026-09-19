#include "tscb_adapter_v1.h"
#include <sys/mman.h>
#include <unistd.h>
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

struct GuardBuffer {
    void* mapping;
    size_t mapped;
    uint8_t* data;
    size_t size;
    explicit GuardBuffer(size_t n): size(n) {
        size_t page = static_cast<size_t>(sysconf(_SC_PAGESIZE));
        size_t accessible = ((std::max<size_t>(1, n) + page) / page) * page;
        mapped = accessible + 2 * page;
        mapping = mmap(nullptr, mapped, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(mapping != MAP_FAILED);
        auto* base = static_cast<uint8_t*>(mapping) + page;
        assert(mprotect(base, accessible, PROT_READ | PROT_WRITE) == 0);
        std::memset(base, 0xa5, accessible);
        data = base + accessible - std::max<size_t>(1, n);
    }
    ~GuardBuffer() { assert(munmap(mapping, mapped) == 0); }
    void canary() const { assert(data[-1] == 0xa5); }
};

static tscb_buffer_v1 buffer(void* p, size_t capacity, size_t used) {
    tscb_buffer_v1 result{};
    result.data = p;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = TSCB_DTYPE_BYTES_V1;
    result.rank = 1;
    result.shape[0] = used;
    result.strides_bytes[0] = 1;
    result.alignment_bytes = 1;
    return result;
}

int main() {
    if (!__builtin_cpu_supports("sse4.1")) return 77;
    const char config[] = "{\"compression_level\":12,\"content_checksum\":false}";
    unsigned cases = 0;
    for (size_t n: {0,1,2,7,8,9,15,16,17,31,32,33,63,64,65,255,256,257,
                    479,480,481,511,512,513,1023,1024,1025,4095,4096,4097,
                    65535,65536,65537,131071,131072,131073}) {
        for (unsigned pattern = 0; pattern < 5; ++pattern) {
            tscb_codec_handle_v1* handle = nullptr;
            assert(tscb_create(config, sizeof(config)-1, &handle) == 0);
            assert(tscb_set_native_timing(handle, 1) == 0);
            GuardBuffer input(n), compressed(std::max<size_t>(1,n)), decoded(n);
            uint32_t random = 20260918;
            for (size_t k = 0; k < n; ++k) {
                random ^= random << 13; random ^= random >> 17; random ^= random << 5;
                input.data[k] = pattern == 0 ? 0 : pattern == 1 ? 0xff : pattern == 2 ? k % 251
                    : pattern == 3 ? random & 255 : (k % 23 < 16 ? 42 : random & 255);
            }
            std::vector<uint8_t> frozen(input.data, input.data+n);
            auto in = buffer(input.data,n,n);
            auto out = buffer(compressed.data,std::max<size_t>(1,n),0);
            uint64_t bound = 0;
            assert(tscb_compress_bound(handle,&in,&bound) == 0);
            assert(bound == std::max<size_t>(1,n));
            out.capacity_bytes = bound-1;
            assert(tscb_compress(handle,&in,&out) == TSCB_STATUS_DST_TOO_SMALL_V1);
            out.capacity_bytes = bound;
            assert(tscb_compress(handle,&in,&out) == 0);
            assert(out.used_bytes <= n);
            auto final = buffer(nullptr,0,0);
            assert(tscb_finalize(handle,&final) == 0 && final.used_bytes == 0);
            assert(tscb_finalize(handle,&final) != 0);
            GuardBuffer exact(out.used_bytes);
            std::memcpy(exact.data,compressed.data,out.used_bytes);
            auto stream = buffer(exact.data,out.used_bytes,out.used_bytes);
            auto destination = buffer(decoded.data,n,0);
            assert(tscb_decompress(handle,&stream,&destination) == 0);
            assert(destination.used_bytes == n);
            assert(std::equal(frozen.begin(), frozen.end(), decoded.data));
            assert(std::equal(frozen.begin(), frozen.end(), input.data));
            input.canary(); compressed.canary(); decoded.canary(); exact.canary();
            // Truncated compressed streams must be rejected before unsafe SIMD entry.
            if (out.used_bytes && out.used_bytes < n) {
                for (size_t length = 0; length < out.used_bytes; ++length) {
                    auto truncated = buffer(exact.data,length,length);
                    assert(tscb_decompress(handle,&truncated,&destination) != 0);
                }
            }
            tscb_native_timing_v1 time{};
            time.struct_size = sizeof(time); time.version = 1;
            assert(tscb_get_native_timing(handle,&time) == 0);
            assert(time.native_encode_wall_ns && time.native_decode_wall_ns);
            assert(tscb_reset(handle,0) == 0);
            assert(tscb_get_native_timing(handle,&time) == 0);
            assert(time.native_encode_wall_ns == 0 && time.native_decode_wall_ns == 0);
            assert(tscb_destroy(handle) == 0);
            ++cases;
        }
    }
    // Hostile short streams with exact declared guard-backed input/output buffers.
    tscb_codec_handle_v1* handle = nullptr;
    assert(tscb_create(config,sizeof(config)-1,&handle) == 0);
    uint32_t random = 17;
    for (size_t k = 0; k < 2048; ++k) {
        size_t n = k % 160;
        GuardBuffer input(n), output(512);
        for (size_t i = 0; i < n; ++i) {
            random = random * 1664525 + 1013904223;
            input.data[i] = random >> 24;
        }
        auto in = buffer(input.data,n,n), out = buffer(output.data,512,0);
        (void)tscb_decompress(handle,&in,&out);
        input.canary(); output.canary();
    }
    assert(tscb_destroy(handle) == 0);
    std::printf("PASS: %u exact-buffer roundtrips, bound-1, canaries, guards, truncated tails, reset/timing; 2048 hostile streams\n",cases);
}
