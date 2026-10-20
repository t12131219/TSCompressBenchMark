#pragma once

#include "tsbench_core.hpp"
#include <algorithm>
#include <cstdint>
#include <memory>

// Shared mechanics for the byte algorithms, never the historical C1 API.
namespace tsbench_bytes {
using namespace tsbench_core;
struct Context : State {
    bool decoder;
    size_t bytes;
    explicit Context(const tsbench_core_config& config, bool decoding)
        : decoder(decoding), bytes(input_bytes(config)) {
        if (config.model && *config.model) throw Unsupported("byte codec has no external model");
    }
};
inline void arguments(Context* context, const uint8_t* input, size_t size,
                      uint8_t* output, size_t capacity, tsbench_core_result* result) {
    require(context && result && (!size || input) && (!capacity || output), "invalid direct byte buffers");
    if (size && capacity) {
        auto a = reinterpret_cast<uintptr_t>(input), b = reinterpret_cast<uintptr_t>(output);
        require(size <= UINTPTR_MAX - a && capacity <= UINTPTR_MAX - b,
                "direct byte buffer address overflow");
        require(a + size <= b || b + capacity <= a, "direct byte buffers overlap");
    }
    *result = {};
}
inline void encoding(Context* context, size_t size) {
    require(context && !context->decoder && size == context->bytes,
            "direct byte encoder input differs from task geometry");
}
inline void decoding(Context* context, size_t capacity) {
    require(context && context->decoder, "direct byte decoder context required");
    if (capacity < context->bytes) throw Capacity("direct byte decoder destination is too small");
}
inline void put64(uint8_t* data, uint64_t value) {
    for (unsigned i=0;i<8;++i) data[i]=static_cast<uint8_t>(value>>(8*i));
}
inline uint64_t get64(const uint8_t* data) {
    uint64_t value=0;for(unsigned i=0;i<8;++i)value|=uint64_t(data[i])<<(8*i);return value;
}
inline const uint8_t* source(const uint8_t* data) {
    static const uint8_t empty=0;return data ? data : &empty;
}
inline uint8_t* destination(uint8_t* data, uint8_t& empty) { return data ? data : &empty; }
template<class Codec> int create(const tsbench_core_config* config, int decoder, void** result) {
    return guard(nullptr,[&]{
        require(config && result && (decoder==0 || decoder==1),"invalid direct byte creation");
        *result=nullptr;auto context=std::make_unique<Codec>(*config,decoder!=0);*result=context.release();
    });
}
} // namespace tsbench_bytes

#define TSBENCH_BYTE_COMMON_API(Codec) \
extern "C" uint32_t tsbench_core_version(void) { return 1; } \
extern "C" int tsbench_core_create(const tsbench_core_config* c,int decoder,void** out) { return tsbench_bytes::create<Codec>(c,decoder,out); } \
extern "C" int tsbench_core_destroy(void* raw) { delete static_cast<Codec*>(raw);return 0; } \
extern "C" void tsbench_core_release(tsbench_core_result* r) { tsbench_core::release(r); } \
extern "C" const char* tsbench_core_error(void* raw) { return raw ? static_cast<Codec*>(raw)->error.c_str() : tsbench_core::last_error().c_str(); }
