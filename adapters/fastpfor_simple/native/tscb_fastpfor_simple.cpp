// Bounded C ABI around unchanged FastPFOR Simple9/Simple16 public APIs.
#include "tscb_native_timing.h"
#include "simple9.h"
#include "simple16.h"
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>
#include <array>
#include <exception>

namespace {
constexpr uint32_t max_count = 16777216;
constexpr uint64_t overhead = 40;
using Status = tscb_status_v1;
using Words = std::vector<uint32_t>;
using Codec = FastPForLib::IntegerCODEC;
struct Layout { unsigned count; std::array<unsigned, 28> widths; };
constexpr Layout s9[] = {
    {28,{1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}},
    {14,{2,2,2,2,2,2,2,2,2,2,2,2,2,2}}, {9,{3,3,3,3,3,3,3,3,3}},
    {7,{4,4,4,4,4,4,4}}, {5,{5,5,5,5,5}}, {4,{7,7,7,7}},
    {3,{9,9,9}}, {2,{14,14}}, {1,{28}}
};
constexpr Layout s16[] = {
    s9[0], {21,{2,2,2,2,2,2,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1}},
    {21,{1,1,1,1,1,1,1,2,2,2,2,2,2,2,1,1,1,1,1,1,1}},
    {21,{1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2}}, s9[1],
    {9,{4,3,3,3,3,3,3,3,3}}, {8,{3,4,4,4,4,3,3,3}}, s9[3],
    {6,{5,5,5,5,4,4}}, {6,{4,4,5,5,5,5}}, {5,{6,6,6,5,5}},
    {5,{5,5,6,6,6}}, s9[5], {3,{10,9,9}}, s9[7], s9[8]
};
bool span(const void* p, uint64_t n) {
    return n <= SIZE_MAX && (!n || (p && n <= UINTPTR_MAX - reinterpret_cast<uintptr_t>(p)));
}
bool common(const tscb_buffer_v1* b) {
    if (!b || b->rank != 1 || b->reserved || b->ownership > TSCB_OWNERSHIP_CODEC_V1
        || b->used_bytes > b->capacity_bytes || !span(b->data, b->capacity_bytes)
        || !b->alignment_bytes || b->alignment_bytes > SIZE_MAX
        || (b->alignment_bytes & (b->alignment_bytes - 1))
        || (b->data && reinterpret_cast<uintptr_t>(b->data) % b->alignment_bytes)) return false;
    for (unsigned i = 1; i < TSCB_MAX_RANK_V1; ++i)
        if (b->shape[i] || b->strides_bytes[i]) return false;
    return true;
}
bool vector(const tscb_buffer_v1* b, bool source) {
    return common(b) && b->dtype == TSCB_DTYPE_U32_LE_V1
        && !(b->capacity_bytes % 4) && !(b->used_bytes % 4) && b->strides_bytes[0] == 4
        && b->shape[0] == (source ? b->used_bytes : b->capacity_bytes) / 4
        && (source || !b->used_bytes);
}
bool bytes(const tscb_buffer_v1* b) {
    return common(b) && b->dtype == TSCB_DTYPE_BYTES_V1 && b->strides_bytes[0] == 1
        && b->shape[0] == b->capacity_bytes;
}
bool alias(const void* a, uint64_t na, const void* b, uint64_t nb) {
    if (!na || !nb) return false;
    const auto x = reinterpret_cast<uintptr_t>(a), y = reinterpret_cast<uintptr_t>(b);
    return x <= y ? y - x < na : x - y < nb;
}
uint32_t get32(const unsigned char* p) {
    uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) value |= uint32_t(p[i]) << (8 * i);
    return value;
}
uint64_t get64(const unsigned char* p) {
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= uint64_t(p[i]) << (8 * i);
    return value;
}
void put32(unsigned char* p, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) p[i] = static_cast<unsigned char>(value >> (8 * i));
}
void put64(unsigned char* p, uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<unsigned char>(value >> (8 * i));
}
uint64_t checksum(const unsigned char* p, uint64_t n) {
    uint64_t value = UINT64_C(14695981039346656037);
    for (uint64_t i = 0; i < n; ++i) value = (value ^ p[i]) * UINT64_C(1099511628211);
    return value;
}
std::unique_ptr<Codec> make_codec(uint32_t kind, bool marked) {
    if (kind == 2) {
        if (marked) return std::make_unique<FastPForLib::Simple16<true>>();
        return std::make_unique<FastPForLib::Simple16<false>>();
    }
    if (kind == 1) {
        if (marked) return std::make_unique<FastPForLib::Simple9<true,true>>();
        return std::make_unique<FastPForLib::Simple9<false,true>>();
    }
    if (marked) return std::make_unique<FastPForLib::Simple9<true>>();
    return std::make_unique<FastPForLib::Simple9<false>>();
}
// Validate grammar/count/tail before calling the original unbounded decoder.
// It performs no reconstruction; decoded values come from the original API.
bool inspect(const Words& input, uint32_t n, uint32_t kind, bool marked,
             uint64_t& value_bits, uint64_t& padding_bits) {
    if (marked && (input.empty() || input[0] != n)) return false;
    size_t at = marked ? 1 : 0;
    uint32_t logical = 0;
    value_bits = padding_bits = 0;
    while (logical < n) {
        if (at == input.size()) return false;
        const uint32_t word = input[at++], selector = word >> 28;
        if (kind != 2 && selector >= (kind == 1 ? 10U : 9U)) return false;
        const bool zero = kind == 1 && selector == 9;
        const Layout& layout = kind == 2 ? s16[selector] : s9[zero ? 0 : selector];
        const unsigned used = std::min<uint32_t>(n - logical, layout.count);
        unsigned widths = 0;
        if (!zero) for (unsigned i = 0; i < used; ++i) widths += layout.widths[i];
        const unsigned spare = 28 - widths;
        const uint32_t mask = (uint32_t(1) << spare) - 1;
        if ((word & mask) || (zero && (word & 0x0fffffffU))) return false;
        value_bits += widths;
        padding_bits += spare;
        logical += used;
    }
    return at == input.size();
}
// C++ exceptions must still end the timer before crossing the C ABI.
struct Interval {
    tscb_native_timer& timer;
    uint64_t& total;
    uint64_t start;
    Interval(tscb_native_timer& t, uint64_t& sum) : timer(t), total(sum), start(tscb_native_now(&t)) {}
    ~Interval() {
        const uint64_t end = tscb_native_now(&timer);
        if (!timer.enabled || !timer.available) return;
        if (end < start || UINT64_MAX - total < end - start) timer.available = 0;
        else total += end - start;
    }
};
}

struct tscb_codec_handle_v1 {
    uint32_t kind = 0;
    bool marked = true, updated = false, finalized = false;
    uint32_t count = 0, words = 0;
    uint64_t value_bits = 0, padding_bits = 0;
    tscb_native_timer native_timer{1,1,0,0};
    char last_error[256]{}, accounting[512]{}, telemetry[1024]{};
};

namespace {
Status fail(tscb_codec_handle_v1* h, Status status, const char* error) {
    if (h) std::snprintf(h->last_error, sizeof(h->last_error), "%s", error);
    return status;
}
void telemetry(tscb_codec_handle_v1* h, uint32_t n, uint32_t words, bool marked, bool encode) {
    const uint64_t input_bytes = encode ? uint64_t(n + 28) * 4 : uint64_t(std::max(words,1U)) * 4;
    const uint64_t output_bytes = encode ? uint64_t(std::max(n + (marked ? 1U : 0U),1U)) * 4 : uint64_t(n + 28) * 4;
    std::snprintf(h->telemetry, sizeof(h->telemetry),
        "{\"actual_original_api\":\"%s\",\"codec_variant\":%u,\"mark_length\":%s,"
        "\"scope\":\"ONE_%s_OBJECT\",\"native_payload_bytes\":%llu,"
        "\"native_raw_bytes\":%llu,\"native_staging_allocation_bytes\":%llu,"
        "\"native_staging_allocation_count\":2,\"internal_padding_bytes\":112,"
        "\"native_staging_input_copy_bytes\":%llu,\"native_staging_output_copy_bytes\":%llu}",
        encode ? "FastPForLib::encodeArray" : "FastPForLib::decodeArray", h->kind,
        marked ? "true" : "false", encode ? "ENCODE" : "DECODE",
        static_cast<unsigned long long>(words) * 4,
        static_cast<unsigned long long>(n) * 4,
        static_cast<unsigned long long>(input_bytes + output_bytes),
        static_cast<unsigned long long>(encode ? uint64_t(n)*4 : uint64_t(words)*4),
        static_cast<unsigned long long>(encode ? uint64_t(words)*4 : uint64_t(n)*4));
}
}

extern "C" {
uint32_t tscb_get_abi_version(void) { return TSCB_ADAPTER_ABI_V1; }
Status tscb_get_manifest_json(const char** p, uint64_t* n) {
    static constexpr char manifest[] =
        "{\"abi_version\":1,\"algorithm\":\"fastpfor-simple-source\",\"isa\":\"SCALAR\","
        "\"frame\":\"SPF1\",\"encoder\":\"ORIGINAL_PUBLIC_API\","
        "\"decoder\":\"ORIGINAL_PUBLIC_API_VALIDATED_GRAMMAR\","
        "\"source_patch\":\"NONE\",\"value_bits_max\":28,\"external_padding_bytes\":0}";
    if (!p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = manifest; *n = sizeof(manifest) - 1; return TSCB_STATUS_OK_V1;
}
Status tscb_create(const char* config, uint64_t size, tscb_codec_handle_v1** handle) {
    if (!handle) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *handle = nullptr;
    if (size > 128 || !span(config,size) || !config) return TSCB_STATUS_INVALID_ARGUMENT_V1;
#if !defined(__x86_64__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
    return TSCB_STATUS_UNSUPPORTED_V1;
#endif
    const char* names[] = {"SIMPLE9", "SIMPLE9HACKED", "SIMPLE16"};
    for (uint32_t kind = 0; kind < 3; ++kind) for (bool marked : {false,true}) {
        char expected[128];
        int length = std::snprintf(expected, sizeof(expected),
            "{\"codec\":\"%s\",\"isa\":\"SCALAR\",\"mark_length\":%s}",
            names[kind], marked ? "true" : "false");
        if (size != static_cast<uint64_t>(length) || std::memcmp(config, expected, size)) continue;
        try {
            auto h = std::make_unique<tscb_codec_handle_v1>();
            h->kind = kind; h->marked = marked; *handle = h.release();
            return TSCB_STATUS_OK_V1;
        } catch (...) { return TSCB_STATUS_CODEC_ERROR_V1; }
    }
    return TSCB_STATUS_INVALID_ARGUMENT_V1;
}
Status tscb_destroy(tscb_codec_handle_v1* h) { delete h; return TSCB_STATUS_OK_V1; }
Status tscb_reset(tscb_codec_handle_v1* h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    h->updated = h->finalized = false;
    h->count = h->words = 0; h->value_bits = h->padding_bits = 0;
    h->native_timer.available = 1; h->native_timer.encode_ns = h->native_timer.decode_ns = 0;
    h->last_error[0] = h->telemetry[0] = h->accounting[0] = '\0';
    return TSCB_STATUS_OK_V1;
}
TSCB_NATIVE_TIMING_API
Status tscb_compress_bound(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, uint64_t* bound) {
    if (!h || !bound || !vector(in,true)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (in->shape[0] > max_count) return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"count resource limit");
    *bound = overhead + in->used_bytes + (h->marked ? 4 : 0); return TSCB_STATUS_OK_V1;
}
Status tscb_compress(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, tscb_buffer_v1* out) {
    if (!h || !vector(in,true) || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (h->updated || h->finalized) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"update lifecycle");
    if (in->shape[0] > max_count) return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"count resource limit");
    if (alias(in->data,in->used_bytes,out->data,out->capacity_bytes))
        return fail(h,TSCB_STATUS_INVALID_ARGUMENT_V1,"input/output alias");
    const auto* p = static_cast<const unsigned char*>(in->data);
    const uint32_t n = static_cast<uint32_t>(in->shape[0]);
    for (uint32_t i = 0; i < n; ++i)
        if (get32(p + uint64_t(i)*4) >= (uint32_t(1) << 28))
            return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"value exceeds original 28-bit source domain");
    try {
        Words input(n + 28,0), encoded(std::max(n + (h->marked ? 1U : 0U),1U),0);
        if (n) std::memcpy(input.data(), in->data, in->used_bytes);
        auto codec = make_codec(h->kind,h->marked);
        size_t used = encoded.size();
        { Interval timer(h->native_timer,h->native_timer.encode_ns);
          codec->encodeArray(input.data(),n,encoded.data(),used); }
        if (used > n + (h->marked ? 1U : 0U))
            return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"source exceeded proved bound");
        encoded.resize(used);
        uint64_t value_bits, padding_bits;
        if (!inspect(encoded,n,h->kind,h->marked,value_bits,padding_bits))
            return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"source produced invalid selector stream");
        const uint64_t length = overhead + uint64_t(used)*4;
        if (out->capacity_bytes < length) return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"exact stream capacity");
        auto* target = static_cast<unsigned char*>(out->data);
        std::memcpy(target,"TSCBSPF1",8); put32(target+8,n); put32(target+12,h->kind);
        put32(target+16,h->marked); put32(target+20,static_cast<uint32_t>(used));
        put32(target+24,0); put32(target+28,0);
        for (size_t i = 0; i < used; ++i) put32(target+32+i*4,encoded[i]);
        put64(target+length-8,checksum(target,length-8));
        out->used_bytes = length; h->updated = true; h->count = n; h->words = static_cast<uint32_t>(used);
        h->value_bits = value_bits; h->padding_bits = padding_bits;
        telemetry(h,n,h->words,h->marked,true); return TSCB_STATUS_OK_V1;
    } catch (const std::exception& e) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,e.what()); }
      catch (...) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"unknown source exception"); }
}
Status tscb_finalize(tscb_codec_handle_v1* h, tscb_buffer_v1* out) {
    if (!h || !bytes(out) || out->used_bytes) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (h->finalized) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"finalize lifecycle");
    h->finalized = true; return TSCB_STATUS_OK_V1;
}
Status tscb_decompress(tscb_codec_handle_v1* h, const tscb_buffer_v1* in, tscb_buffer_v1* out) {
    if (!h || !bytes(in) || !vector(out,false)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (alias(in->data,in->used_bytes,out->data,out->capacity_bytes))
        return fail(h,TSCB_STATUS_INVALID_ARGUMENT_V1,"input/output alias");
    if (in->used_bytes < overhead) return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"truncated SPF1");
    const auto* p = static_cast<const unsigned char*>(in->data);
    const uint32_t n = get32(p+8), kind = get32(p+12), marked = get32(p+16), words = get32(p+20);
    if (std::memcmp(p,"TSCBSPF1",8) || n > max_count || kind != h->kind || marked > 1
        || words > n + marked || get32(p+24) || get32(p+28)
        || in->used_bytes != overhead + uint64_t(words)*4)
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"SPF1 identity/geometry");
    if (get64(p+in->used_bytes-8) != checksum(p,in->used_bytes-8))
        return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"SPF1 checksum");
    if (out->capacity_bytes < uint64_t(n)*4)
        return fail(h,TSCB_STATUS_DST_TOO_SMALL_V1,"decode capacity");
    try {
        Words input(std::max(words,1U),0), decoded(n+28,0);
        for (uint32_t i = 0; i < words; ++i) input[i] = get32(p+32+uint64_t(i)*4);
        input.resize(words);
        uint64_t value_bits, padding_bits;
        if (!inspect(input,n,kind,marked,value_bits,padding_bits))
            return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"invalid selector/count/tail stream");
        auto codec = make_codec(kind,marked);
        size_t count = n;
        const uint32_t* consumed;
        { Interval timer(h->native_timer,h->native_timer.decode_ns);
          consumed = codec->decodeArray(input.data(),words,decoded.data(),count); }
        if (count != n || consumed != input.data()+words)
            return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"source decode count/consumption");
        if (n) std::memcpy(out->data,decoded.data(),uint64_t(n)*4);
        out->used_bytes = uint64_t(n)*4;
        telemetry(h,n,words,marked,false); return TSCB_STATUS_OK_V1;
    } catch (const std::exception& e) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,e.what()); }
      catch (...) { return fail(h,TSCB_STATUS_CODEC_ERROR_V1,"unknown source exception"); }
}
Status tscb_get_accounting_json(tscb_codec_handle_v1* h, const char** p, uint64_t* n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->finalized) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    const uint64_t selectors = h->words - (h->marked ? 1 : 0);
    std::snprintf(h->accounting,sizeof(h->accounting),
        "{\"container_bits\":64,\"metadata_bits\":%llu,\"checksum_bits\":64,"
        "\"value_bits\":%llu,\"padding_bits\":%llu,\"final_bits\":%llu,"
        "\"count\":%u,\"original_payload_bytes\":%llu,\"external_padding_bytes\":0}",
        static_cast<unsigned long long>(192 + (h->marked ? 32 : 0) + selectors*4),
        static_cast<unsigned long long>(h->value_bits),static_cast<unsigned long long>(h->padding_bits),
        static_cast<unsigned long long>((overhead+uint64_t(h->words)*4)*8),h->count,
        static_cast<unsigned long long>(h->words)*4);
    *p = h->accounting; *n = std::strlen(*p); return TSCB_STATUS_OK_V1;
}
Status tscb_get_telemetry_json(tscb_codec_handle_v1* h, const char** p, uint64_t* n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    if (!h->telemetry[0]) return TSCB_STATUS_UNSUPPORTED_V1;
    *p = h->telemetry; *n = std::strlen(*p); return TSCB_STATUS_OK_V1;
}
Status tscb_get_last_error(tscb_codec_handle_v1* h, const char** p, uint64_t* n) {
    if (!h || !p || !n) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *p = h->last_error; *n = std::strlen(*p); return TSCB_STATUS_OK_V1;
}
Status tscb_query(tscb_codec_handle_v1* h, const char*, uint64_t, char*, uint64_t, uint64_t*) {
    if (!h) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return fail(h,TSCB_STATUS_UNSUPPORTED_V1,"query workload not admitted");
}
}
