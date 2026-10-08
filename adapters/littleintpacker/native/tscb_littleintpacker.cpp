// Bounded ABI: use the recorded corrected LittleIntPacker kernels unchanged.
#include "tscb_native_timing.h"
extern "C" {
#include "bitpacking.h"
#include "util.h"
}
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <exception>
#include <memory>
#include <vector>

namespace {
using Status = tscb_status_v1;
constexpr uint32_t max_count = 16777216;
constexpr uint64_t overhead = 40;
constexpr uint64_t pack_padding = 136, unpack_padding = 528;
using Pack = void (*)(const uint32_t*, uint32_t, uint32_t, uint8_t*);
using Unpack = void (*)(const uint8_t*, uint32_t, uint32_t, uint32_t*);
const Pack packers[] = {pack32, turbopack32, scpack32, bmipack32, pack32};
const Unpack unpackers[] = {unpack32, turbounpack32, scunpack32, bmiunpack32, horizontalunpack32};
const char* names[] = {"PACK32", "TURBO", "SC", "BMI2", "HORIZONTAL"};
const char* pack_names[] = {"pack32", "turbopack32", "scpack32", "bmipack32", "pack32"};
const char* unpack_names[] = {"unpack32", "turbounpack32", "scunpack32", "bmiunpack32", "horizontalunpack32"};
const char* isas[] = {"SCALAR", "SCALAR", "SCALAR", "AVX2_BMI2", "SSE4_1"};
bool span(const void* p, uint64_t n) {
    return n <= SIZE_MAX && (!n || (p && n <= UINTPTR_MAX - reinterpret_cast<uintptr_t>(p)));
}
bool common(const tscb_buffer_v1* b) {
    if (!b || b->rank != 1 || b->reserved || b->ownership > TSCB_OWNERSHIP_CODEC_V1
        || b->used_bytes > b->capacity_bytes || !span(b->data,b->capacity_bytes)
        || !b->alignment_bytes || b->alignment_bytes > SIZE_MAX
        || (b->alignment_bytes & (b->alignment_bytes-1))
        || (b->data && reinterpret_cast<uintptr_t>(b->data) % b->alignment_bytes)) return false;
    for (unsigned i=1; i<TSCB_MAX_RANK_V1; ++i)
        if (b->shape[i] || b->strides_bytes[i]) return false;
    return true;
}
bool values(const tscb_buffer_v1* b, bool input) {
    return common(b) && b->dtype == TSCB_DTYPE_U32_LE_V1 && !(b->capacity_bytes%4)
        && !(b->used_bytes%4) && b->strides_bytes[0] == 4
        && b->shape[0] == (input ? b->used_bytes : b->capacity_bytes)/4
        && (input || !b->used_bytes);
}
bool bytes(const tscb_buffer_v1* b) {
    return common(b) && b->dtype == TSCB_DTYPE_BYTES_V1 && b->strides_bytes[0] == 1
        && b->shape[0] == b->capacity_bytes;
}
bool overlaps(const void* a, uint64_t na, const void* b, uint64_t nb) {
    if (!na || !nb) return false;
    const auto x=reinterpret_cast<uintptr_t>(a), y=reinterpret_cast<uintptr_t>(b);
    return x <= y ? y-x < na : x-y < nb;
}
uint32_t read32(const unsigned char* p) {
    uint32_t v=0; for (unsigned i=0;i<4;++i) v |= uint32_t(p[i]) << (8*i); return v;
}
uint64_t read64(const unsigned char* p) {
    uint64_t v=0; for (unsigned i=0;i<8;++i) v |= uint64_t(p[i]) << (8*i); return v;
}
void write32(unsigned char* p, uint32_t v) {
    for (unsigned i=0;i<4;++i) p[i]=static_cast<unsigned char>(v >> (8*i));
}
void write64(unsigned char* p, uint64_t v) {
    for (unsigned i=0;i<8;++i) p[i]=static_cast<unsigned char>(v >> (8*i));
}
uint64_t checksum(const unsigned char* p, uint64_t n) {
    uint64_t v=UINT64_C(14695981039346656037);
    for (uint64_t i=0;i<n;++i) v=(v^p[i])*UINT64_C(1099511628211);
    return v;
}
struct Interval {
    tscb_native_timer& timer;
    uint64_t& total;
    uint64_t start;
    int exceptions;
    Interval(tscb_native_timer& t, uint64_t& sum)
        : timer(t),total(sum),start(tscb_native_now(&t)),exceptions(std::uncaught_exceptions()) {}
    ~Interval() {
        const uint64_t end=tscb_native_now(&timer);
        if (std::uncaught_exceptions()>exceptions) { timer.available=0; return; }
        if (!timer.enabled || !timer.available) return;
        if (end<start || UINT64_MAX-total<end-start) timer.available=0;
        else total+=end-start;
    }
};
bool cpu_available(unsigned kind) {
#if defined(__x86_64__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if (kind==3) return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("bmi2");
    if (kind==4) return __builtin_cpu_supports("ssse3") && __builtin_cpu_supports("sse4.1");
    return true;
#else
    (void)kind; return false;
#endif
}
}

struct tscb_codec_handle_v1 {
    unsigned kind=0, width=32;
    bool automatic=false, updated=false, finalized=false;
    uint32_t count=0, actual_width=0;
    uint64_t payload_bytes=0;
    tscb_native_timer native_timer{0,1,0,0};
    char error[256]{}, accounting[768]{}, telemetry[1280]{};
};

namespace {
Status fail(tscb_codec_handle_v1* h, Status status, const char* message) {
    if (h) std::snprintf(h->error,sizeof(h->error),"%s",message);
    return status;
}
Status width_for(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, unsigned& width) {
    const auto* p=static_cast<const unsigned char*>(in->data);
    uint32_t combined=0;
    for (uint64_t i=0;i<in->shape[0];++i) combined |= read32(p+i*4);
    const unsigned minimum=bits(combined); // Original scalar public helper; outside codec interval.
    width=h->automatic ? minimum : h->width;
    if (minimum>width) return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"value exceeds supplied bit width");
    return TSCB_STATUS_OK_V1;
}
void telemetry(tscb_codec_handle_v1* h, uint32_t n, unsigned width, uint64_t payload, bool encode) {
    const uint64_t staging_in=encode ? uint64_t(n+32)*4 : payload+unpack_padding;
    const uint64_t staging_out=encode ? payload+pack_padding : uint64_t(n+128)*4;
    std::snprintf(h->telemetry,sizeof(h->telemetry),
        "{\"actual_original_api\":\"%s\",\"codec_variant\":\"%s\",\"actual_isa\":\"%s\","
        "\"scope\":\"ONE_%s_OBJECT\",\"native_api_calls\":1,\"count\":%u,\"bit_width\":%u,"
        "\"native_raw_bytes\":%llu,\"native_payload_bytes\":%llu,"
        "\"native_staging_allocation_bytes\":%llu,\"native_staging_allocation_count\":2,"
        "\"native_staging_input_copy_bytes\":%llu,\"native_staging_output_copy_bytes\":%llu,"
        "\"internal_input_padding_bytes\":%llu,\"internal_output_headroom_bytes\":%llu,"
        "\"external_padding_bytes\":0}",
        encode?pack_names[h->kind]:unpack_names[h->kind], names[h->kind],
        encode && h->kind==4 ? "SCALAR" : isas[h->kind], encode?"ENCODE":"DECODE", n,width,
        static_cast<unsigned long long>(n)*4,static_cast<unsigned long long>(payload),
        static_cast<unsigned long long>(staging_in+staging_out),
        static_cast<unsigned long long>(encode?uint64_t(n)*4:payload),
        static_cast<unsigned long long>(encode?payload:uint64_t(n)*4),
        static_cast<unsigned long long>(encode?128:unpack_padding),
        static_cast<unsigned long long>(encode?pack_padding:512));
}
}

extern "C" {
uint32_t tscb_get_abi_version() { return TSCB_ADAPTER_ABI_V1; }
Status tscb_get_manifest_json(const char** p, uint64_t* n) {
    static constexpr char json[]=
        "{\"abi_version\":1,\"algorithm\":\"littleintpacker-source\",\"frame\":\"LIP1\","
        "\"encoder\":\"PATCHED_ORIGINAL_PUBLIC_API\",\"decoder\":\"PATCHED_ORIGINAL_PUBLIC_API\","
        "\"variants\":[\"PACK32\",\"TURBO\",\"SC\",\"BMI2\",\"HORIZONTAL\"],"
        "\"external_padding_bytes\":0,\"max_count\":16777216,\"bit_width_min\":0,\"bit_width_max\":32}";
    if (!p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p=json; *n=sizeof(json)-1; return TSCB_STATUS_OK_V1;
}
Status tscb_create(const char* config, uint64_t length, tscb_codec_handle_v1** result) {
    if (!result) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *result=nullptr;
    if (!config || length>160 || !span(config,length)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    for (unsigned kind=0;kind<5;++kind) for (unsigned width=0;width<=33;++width) {
        char expected[160], width_json[16];
        if (width==33) std::snprintf(width_json,sizeof(width_json),"\"AUTO\"");
        else std::snprintf(width_json,sizeof(width_json),"%u",width);
        const int size=std::snprintf(expected,sizeof(expected),
            "{\"bit_width\":%s,\"codec\":\"%s\",\"isa\":\"%s\"}",width_json,names[kind],isas[kind]);
        if (length != static_cast<uint64_t>(size) || std::memcmp(config,expected,length)) continue;
        if (!cpu_available(kind)) return TSCB_STATUS_UNSUPPORTED_V1;
        try {
            auto h=std::make_unique<tscb_codec_handle_v1>();
            h->kind=kind; h->automatic=width==33; h->width=h->automatic?32:width;
            *result=h.release(); return TSCB_STATUS_OK_V1;
        } catch (...) { return TSCB_STATUS_CODEC_ERROR_V1; }
    }
    return TSCB_STATUS_INVALID_ARGUMENT_V1;
}
Status tscb_destroy(tscb_codec_handle_v1* h) { delete h; return TSCB_STATUS_OK_V1; }
Status tscb_reset(tscb_codec_handle_v1* h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    h->updated=h->finalized=false; h->count=h->actual_width=0; h->payload_bytes=0;
    h->native_timer.available=1; h->native_timer.encode_ns=h->native_timer.decode_ns=0;
    h->error[0]=h->accounting[0]=h->telemetry[0]='\0';
    return TSCB_STATUS_OK_V1;
}
TSCB_NATIVE_TIMING_API
Status tscb_compress_bound(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, uint64_t* bound) {
    if (!h || !bound || !values(in,true)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (in->shape[0]>max_count) return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"count resource limit");
    unsigned width;
    const Status status=width_for(h,in,width);
    if (status!=TSCB_STATUS_OK_V1) return status;
    *bound=overhead+(in->shape[0]*width+7)/8; return TSCB_STATUS_OK_V1;
}
Status tscb_compress(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, tscb_buffer_v1* out) {
    if (!h || !values(in,true) || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (h->updated || h->finalized) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"update lifecycle");
    if (in->shape[0]>max_count) return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"count resource limit");
    if (overlaps(in->data,in->used_bytes,out->data,out->capacity_bytes))
        return fail(h,TSCB_STATUS_INVALID_ARGUMENT_V1,"input/output alias");
    unsigned width;
    const Status status=width_for(h,in,width);
    if (status!=TSCB_STATUS_OK_V1) return status;
    const uint32_t n=static_cast<uint32_t>(in->shape[0]);
    const uint64_t value_bits=uint64_t(n)*width, payload=(value_bits+7)/8, size=overhead+payload;
    if (out->capacity_bytes<size) return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"exact stream capacity");
    try {
        std::vector<uint32_t> padded(n+32,0);
        std::vector<unsigned char> encoded(payload+pack_padding,0);
        if (n) std::memcpy(padded.data(),in->data,uint64_t(n)*4);
        { Interval interval(h->native_timer,h->native_timer.encode_ns);
          packers[h->kind](padded.data(),n,width,encoded.data()); }
        if (value_bits%8 && (encoded[payload-1] >> (value_bits%8)))
            return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"source produced nonzero tail padding");
        auto* p=static_cast<unsigned char*>(out->data);
        std::memcpy(p,"TSCBLIP1",8); write32(p+8,n); write32(p+12,h->kind);
        write32(p+16,width); write32(p+20,h->automatic?1:0); write64(p+24,payload);
        if (payload) std::memcpy(p+32,encoded.data(),payload);
        write64(p+size-8,checksum(p,size-8));
        out->used_bytes=size; h->updated=true; h->count=n; h->actual_width=width; h->payload_bytes=payload;
        telemetry(h,n,width,payload,true); return TSCB_STATUS_OK_V1;
    } catch (const std::exception& e) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,e.what()); }
      catch (...) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"unknown source exception"); }
}
Status tscb_finalize(tscb_codec_handle_v1* h, tscb_buffer_v1* out) {
    if (!h || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (h->finalized) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"finalize lifecycle");
    h->finalized=true; return TSCB_STATUS_OK_V1;
}
Status tscb_decompress(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, tscb_buffer_v1* out) {
    if (!h || !bytes(in) || !values(out,false)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (overlaps(in->data,in->used_bytes,out->data,out->capacity_bytes))
        return fail(h,TSCB_STATUS_INVALID_ARGUMENT_V1,"input/output alias");
    if (in->used_bytes<overhead) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"truncated LIP1");
    const auto* p=static_cast<const unsigned char*>(in->data);
    const uint32_t n=read32(p+8), kind=read32(p+12), width=read32(p+16), mode=read32(p+20);
    const uint64_t payload=read64(p+24), value_bits=uint64_t(n)*width;
    if (std::memcmp(p,"TSCBLIP1",8) || n>max_count || kind!=h->kind || width>32 || mode>1
        || payload!=(value_bits+7)/8 || payload>uint64_t(max_count)*4
        || in->used_bytes!=overhead+payload)
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"LIP1 identity/geometry");
    if (read64(p+in->used_bytes-8)!=checksum(p,in->used_bytes-8))
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"LIP1 checksum");
    if (value_bits%8 && (p[32+payload-1] >> (value_bits%8)))
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"nonzero payload tail padding");
    if (out->capacity_bytes<uint64_t(n)*4) return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"decode capacity");
    try {
        std::vector<unsigned char> packed(payload+unpack_padding,0);
        std::vector<uint32_t> decoded(n+128,0);
        // HORIZONTAL uses aligned SIMD stores; reject an incompatible allocator safely.
        if (kind==4 && reinterpret_cast<uintptr_t>(decoded.data())%16)
            return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"internal SIMD allocation alignment");
        if (payload) std::memcpy(packed.data(),p+32,payload);
        { Interval interval(h->native_timer,h->native_timer.decode_ns);
          unpackers[kind](packed.data(),n,width,decoded.data()); }
        if (mode) {
            uint32_t combined=0; for (uint32_t i=0;i<n;++i) combined |= decoded[i];
            if (bits(combined)!=width) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"noncanonical AUTO width");
        }
        if (n) std::memcpy(out->data,decoded.data(),uint64_t(n)*4);
        out->used_bytes=uint64_t(n)*4;
        telemetry(h,n,width,payload,false); return TSCB_STATUS_OK_V1;
    } catch (const std::exception& e) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,e.what()); }
      catch (...) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"unknown source exception"); }
}
Status tscb_get_accounting_json(tscb_codec_handle_v1* h, const char** p, uint64_t* n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    const uint64_t value_bits=uint64_t(h->count)*h->actual_width;
    std::snprintf(h->accounting,sizeof(h->accounting),
        "{\"container_bits\":64,\"metadata_bits\":192,\"checksum_bits\":64,"
        "\"value_bits\":%llu,\"padding_bits\":%llu,\"final_bits\":%llu,"
        "\"count\":%u,\"bit_width\":%u,\"codec_variant\":\"%s\",\"width_mode\":\"%s\","
        "\"original_payload_bytes\":%llu,\"external_padding_bytes\":0}",
        static_cast<unsigned long long>(value_bits),
        static_cast<unsigned long long>(h->payload_bytes*8-value_bits),
        static_cast<unsigned long long>((overhead+h->payload_bytes)*8),h->count,h->actual_width,
        names[h->kind],h->automatic?"AUTO":"FIXED",static_cast<unsigned long long>(h->payload_bytes));
    *p=h->accounting; *n=std::strlen(*p); return TSCB_STATUS_OK_V1;
}
Status tscb_get_telemetry_json(tscb_codec_handle_v1* h, const char** p, uint64_t* n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->telemetry[0]) return TSCB_STATUS_UNSUPPORTED_V1;
    *p=h->telemetry; *n=std::strlen(*p); return TSCB_STATUS_OK_V1;
}
Status tscb_get_last_error(tscb_codec_handle_v1* h, const char** p, uint64_t* n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p=h->error; *n=std::strlen(*p); return TSCB_STATUS_OK_V1;
}
Status tscb_query(tscb_codec_handle_v1* h, const char*, uint64_t, char*, uint64_t, uint64_t*) {
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"query workload not admitted");
}
}
