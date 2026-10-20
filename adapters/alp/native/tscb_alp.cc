// Bench binding only. The frozen safe-v1 API and its core are compiled unchanged.
#include "tscb_native_timing.h"
#include "tsbench_core.hpp"
#include "alp_port.h"
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

struct tscb_codec_handle_v1 {
    tscb_native_timer native_timer{};
    bool updated{}, finalized{};
    uint64_t input_bytes{}, stream_bytes{};
    char error[256]{}, accounting[384]{};
};
namespace {
#if TSCB_ALP_RD
constexpr uint8_t kMethod = ALP_RD;
constexpr char kAlgorithm[] = "alp-rd";
constexpr char kConfig[] = "{\"algorithm\":\"alp-rd\"}";
constexpr char kManifest[] = "{\"abi_version\":1,\"algorithm\":\"alp-rd\",\"implementation\":\"cwida-alp-native-safe-v1\",\"route\":\"NATIVE_PORT\",\"scheme\":\"FORCED_ALP_RD\",\"isa\":\"SCALAR\",\"profile\":\"PORTABLE\",\"threading\":\"SINGLE_THREAD\",\"frame\":\"ALPRW001\"}";
#else
constexpr uint8_t kMethod = ALP_ADAPTIVE;
constexpr char kAlgorithm[] = "alp";
constexpr char kConfig[] = "{\"algorithm\":\"alp\"}";
constexpr char kManifest[] = "{\"abi_version\":1,\"algorithm\":\"alp\",\"implementation\":\"cwida-alp-native-safe-v1\",\"route\":\"NATIVE_PORT\",\"scheme\":\"ADAPTIVE_ALP_OR_RD\",\"isa\":\"SCALAR\",\"profile\":\"PORTABLE\",\"threading\":\"SINGLE_THREAD\",\"frame\":\"ALPRW001\"}";
#endif
void port_check(int status) {
    if (status == ALP_OK) return;
    if (status == ALP_CAPACITY) throw tsbench_core::Capacity("ALP output capacity");
    if (status == ALP_FP_ENV || status == ALP_RESOURCE_LIMIT)
        throw tsbench_core::Unsupported(alp_port_status_string(status));
    throw std::runtime_error(alp_port_status_string(status));
}
void direct_parameters(const char* source) {
    // Resolve the flat JSON syntax first, then enforce the complete whitelist.
    tsbench_core::Parameters parsed(source);
    if (parsed.contains("isa") && parsed.string("isa") != "SCALAR")
        throw tsbench_core::Unsupported("ALP Bench profile is portable (isa=SCALAR)");
    if (parsed.contains("native_timing")) (void)parsed.boolean("native_timing");
    std::string compact;
    bool quoted = false, escape = false;
    for (const char* p = source ? source : "{}"; *p; ++p) {
        if (quoted || !std::isspace(static_cast<unsigned char>(*p))) compact += *p;
        if (*p == '"' && !escape) quoted = !quoted;
        if (*p == '\\' && !escape) escape = true; else escape = false;
    }
    const std::array<const char*, 8> allowed{{"{}", "{\"isa\":\"SCALAR\"}",
        "{\"native_timing\":true}", "{\"native_timing\":false}",
        "{\"isa\":\"SCALAR\",\"native_timing\":true}", "{\"isa\":\"SCALAR\",\"native_timing\":false}",
        "{\"native_timing\":true,\"isa\":\"SCALAR\"}", "{\"native_timing\":false,\"isa\":\"SCALAR\"}"}};
    if (std::none_of(allowed.begin(), allowed.end(), [&](const char* value) { return compact == value; }))
        throw tsbench_core::Unsupported("unknown ALP direct parameters");
}
bool valid_buffer(const tscb_buffer_v1* b) {
    return b && b->dtype == TSCB_DTYPE_BYTES_V1 && b->rank == 1 &&
        b->used_bytes <= b->capacity_bytes && b->capacity_bytes <= SIZE_MAX &&
        (!b->capacity_bytes || b->data);
}
bool overlap(const void* a, size_t na, const void* b, size_t nb) {
    if (!na || !nb) return false;
    const auto x = reinterpret_cast<uintptr_t>(a), y = reinterpret_cast<uintptr_t>(b);
    return x <= y ? y - x < na : x - y < nb;
}
uint64_t le(const uint8_t* p, size_t n) {
    uint64_t x = 0; for (size_t i = 0; i < n; ++i) x |= uint64_t(p[i]) << (8 * i); return x;
}
void append(std::vector<uint8_t>& out, uint64_t value, size_t n) {
    for (size_t i = 0; i < n; ++i) { out.push_back(static_cast<uint8_t>(value)); value >>= 8; }
}
struct Geometry { uint8_t width; uint16_t columns; uint64_t rows; };
Geometry geometry(const uint8_t* data, size_t length, const char* magic) {
    tsbench_core::require(data && length >= 16 && !std::memcmp(data, magic, 4) && !data[5], "invalid ALP column descriptor");
    Geometry g{data[4], static_cast<uint16_t>(le(data + 6, 2)), le(data + 8, 8)};
    tsbench_core::require((g.width == 4 || g.width == 8) && g.columns && g.rows <= ALP_PORT_MAX_VALUES &&
        g.rows <= ALP_PORT_MAX_VALUES / g.columns, "ALP column geometry exceeds profile");
    return g;
}
size_t raw_bytes(const Geometry& g) { return static_cast<size_t>(g.rows) * g.columns * g.width; }
Geometry input_view(const tscb_buffer_v1* input) {
    tsbench_core::require(valid_buffer(input), "invalid ALP input buffer");
    auto g = geometry(static_cast<const uint8_t*>(input->data), input->used_bytes, "TAI1");
    tsbench_core::require(input->used_bytes - 16 == raw_bytes(g), "ALP input byte count mismatch");
    return g;
}
size_t column_bound(const Geometry& g) {
    size_t bound = 0; port_check(alp_port_bound(g.rows, g.width, kMethod, &bound));
    return tsbench_core::add(16, tsbench_core::multiply(g.columns, tsbench_core::add(8, bound)));
}
template<class F> tscb_status_v1 api_guard(tscb_codec_handle_v1* h, F action) noexcept {
    try { action(); return TSCB_STATUS_OK_V1; }
    catch (const tsbench_core::Capacity& e) { if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what()); return TSCB_STATUS_DST_TOO_SMALL_V1; }
    catch (const tsbench_core::Unsupported& e) { if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what()); return TSCB_STATUS_UNSUPPORTED_V1; }
    catch (const std::exception& e) { if(h)std::snprintf(h->error,sizeof(h->error),"%s",e.what()); return TSCB_STATUS_CODEC_ERROR_V1; }
    catch (...) { if(h)std::snprintf(h->error,sizeof(h->error),"ALP binding failure"); return TSCB_STATUS_CODEC_ERROR_V1; }
}
}
extern "C" {
uint32_t tscb_get_abi_version() { return 1; }
tscb_status_v1 tscb_get_manifest_json(const char** json, uint64_t* length) {
    if (!json || !length) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json = kManifest; *length = sizeof(kManifest) - 1; return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_create(const char* config, uint64_t length, tscb_codec_handle_v1** result) {
    if (!result) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *result = nullptr;
    if (!config || length != sizeof(kConfig) - 1 || std::memcmp(config, kConfig, length)) return TSCB_STATUS_UNSUPPORTED_V1;
    return api_guard(nullptr, [&] { *result = new tscb_codec_handle_v1; });
}
tscb_status_v1 tscb_destroy(tscb_codec_handle_v1* h) { delete h; return TSCB_STATUS_OK_V1; }
tscb_status_v1 tscb_reset(tscb_codec_handle_v1* h, uint32_t mode) {
    if (!h || mode) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    const int timing = h->native_timer.enabled; *h = {}; h->native_timer.enabled = timing; h->native_timer.available = 1;
    return TSCB_STATUS_OK_V1;
}
TSCB_NATIVE_TIMING_API

tscb_status_v1 tscb_compress_bound(tscb_codec_handle_v1* h, const tscb_buffer_v1* input, uint64_t* bound) {
    if (!h || !bound) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *bound = 0; return api_guard(h, [&] { *bound = column_bound(input_view(input)); });
}
tscb_status_v1 tscb_compress(tscb_codec_handle_v1* h, const tscb_buffer_v1* input, tscb_buffer_v1* output) {
    if (!h || !valid_buffer(input) || !valid_buffer(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    output->used_bytes = 0;
    if (overlap(input->data,input->used_bytes,output->data,output->capacity_bytes) || h->updated || h->finalized)
        return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(h, [&] {
        const auto g = input_view(input);
        const auto* source = static_cast<const uint8_t*>(input->data);
        std::vector<uint8_t> stream(source, source + 16);
        std::memcpy(stream.data(), "APS1", 4);
        size_t bound = 0; port_check(alp_port_bound(g.rows,g.width,kMethod,&bound));
        std::vector<uint8_t> frame(bound);
        for (uint16_t c = 0; c < g.columns; ++c) {
            size_t used = 0; int status = 0;
            TSCB_TIME_CODEC(h->native_timer,encode_ns,
                status = alp_port_encode(source + 16 + static_cast<size_t>(c) * g.rows * g.width,
                    g.rows,g.width,kMethod,frame.data(),frame.size(),&used));
            port_check(status); append(stream,used,8); stream.insert(stream.end(),frame.begin(),frame.begin()+used);
        }
        if (output->capacity_bytes < stream.size()) throw tsbench_core::Capacity("ALP column output too small");
        std::memcpy(output->data,stream.data(),stream.size()); output->used_bytes=stream.size();
        h->input_bytes=raw_bytes(g); h->stream_bytes=stream.size(); h->updated=true;
    });
}
tscb_status_v1 tscb_finalize(tscb_codec_handle_v1* h, tscb_buffer_v1* output) {
    if (!h || !valid_buffer(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    output->used_bytes=0;
    if (!h->updated) return TSCB_STATUS_FINALIZE_REQUIRED_V1;
    if (h->finalized) return TSCB_STATUS_CODEC_ERROR_V1;
    h->finalized=true;
    std::snprintf(h->accounting,sizeof(h->accounting),"{\"input_bytes\":%llu,\"complete_column_container_bytes\":%llu,\"native_input_descriptor_bytes\":16,\"finalize_calls\":1,\"implementation\":\"cwida-alp-native-safe-v1\"}",
        static_cast<unsigned long long>(h->input_bytes),static_cast<unsigned long long>(h->stream_bytes));
    return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_decompress(tscb_codec_handle_v1* h, const tscb_buffer_v1* input, tscb_buffer_v1* output) {
    if (!h || !valid_buffer(input) || !valid_buffer(output)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    output->used_bytes=0;
    if (overlap(input->data,input->used_bytes,output->data,output->capacity_bytes)) return TSCB_STATUS_INVALID_ARGUMENT_V1;
    return api_guard(h, [&] {
        const auto* source=static_cast<const uint8_t*>(input->data); const size_t length=input->used_bytes;
        const auto g=geometry(source,length,"APS1"); const size_t total=raw_bytes(g);
        if (output->capacity_bytes<total) throw tsbench_core::Capacity("ALP decoded column output too small");
        // Validate all outer lengths/identities before allocating or decoding.
        size_t offset=16;
        for (uint16_t c=0;c<g.columns;++c) {
            tsbench_core::require(length-offset>=8,"truncated ALP column length"); const uint64_t n=le(source+offset,8); offset+=8;
            tsbench_core::require(n>=32 && n<=length-offset && !std::memcmp(source+offset,"ALPRW001",8) &&
                source[offset+8]==g.width && source[offset+9]==kMethod && le(source+offset+12,8)==g.rows,"ALP column identity mismatch");
            offset+=static_cast<size_t>(n);
        }
        tsbench_core::require(offset==length,"trailing ALP column bytes");
        std::vector<uint8_t> decoded(std::max<size_t>(total,1)); offset=16;
        for (uint16_t c=0;c<g.columns;++c) {
            const size_t n=le(source+offset,8); offset+=8;
            size_t used=0,consumed=0; uint64_t count=0; uint8_t width=0,method=0; int status=0;
            TSCB_TIME_CODEC(h->native_timer,decode_ns,
                status=alp_port_decode(source+offset,n,decoded.data()+static_cast<size_t>(c)*g.rows*g.width,
                    g.rows*g.width,&used,&consumed,&count,&width,&method));
            port_check(status);
            tsbench_core::require(used==g.rows*g.width && consumed==n && count==g.rows && width==g.width && method==kMethod,"ALP decoded identity mismatch");
            offset+=n;
        }
        if(total)std::memcpy(output->data,decoded.data(),total); output->used_bytes=total;
    });
}
tscb_status_v1 tscb_query(tscb_codec_handle_v1*, const char*, uint64_t, char*, uint64_t, uint64_t* used) {
    if(used)*used=0; return TSCB_STATUS_UNSUPPORTED_V1;
}
tscb_status_v1 tscb_get_accounting_json(tscb_codec_handle_v1* h, const char** json, uint64_t* length) {
    if(!h || !json || !length || !h->finalized)return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *json=h->accounting; *length=std::strlen(*json); return TSCB_STATUS_OK_V1;
}
tscb_status_v1 tscb_get_last_error(tscb_codec_handle_v1* h, const char** message, uint64_t* length) {
    if(!h || !message || !length)return TSCB_STATUS_INVALID_ARGUMENT_V1;
    *message=h->error; *length=std::strlen(*message); return TSCB_STATUS_OK_V1;
}
}
#include "direct_core.inc"
