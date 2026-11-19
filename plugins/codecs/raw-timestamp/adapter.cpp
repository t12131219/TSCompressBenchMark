#include "linear_frame.hpp"

namespace wire = tsbench::linear;
struct bmk_context { const char *operation{}; };
namespace {
constexpr auto identifier = "raw-timestamp";
constexpr wire::Magic magic{'B','M','K','R','T','1',0,0};
constexpr size_t limit = 512 * 8;
bool ms(const uint8_t *p, size_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("\"time_unit\"") && json.token(":") &&
           json.token("\"ms\"") && json.token("}") && json.done();
}
bool options(const uint8_t *p, uint64_t n) noexcept {
    wire::Options json(p,n);
    return json.token("{") && json.token("}") && json.done();
}
bmk_status inspect(const bmk_object_view *in, wire::Input &data) noexcept {
    const auto rc = wire::view(in,limit,data);
    if (rc != BMK_OK) return rc;
    return data.dtype == BMK_I64 && ms(data.schema,data.schema_size) ? BMK_OK : BMK_UNSUPPORTED;
}
bmk_status probe(const bmk_object_view *in,const uint8_t *p,uint64_t n,bmk_blob *out) noexcept {
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    wire::Input data;
    const auto rc=inspect(in,data);
    return rc==BMK_OK ? wire::text(out,"{\"mode\":\"batch\",\"role\":\"timestamp\",\"max_rows\":512}") : rc;
}
bmk_status create(const bmk_host_v1 *host,const uint8_t *p,uint64_t n,bmk_context **out) noexcept {
    if (!out) return BMK_BAD_INPUT;
    *out=nullptr;
    if (!wire::valid_host(host)) return BMK_BAD_INPUT;
    if (!options(p,n)) return BMK_BAD_OPTIONS;
    *out=new (std::nothrow) bmk_context;
    return *out ? BMK_OK : BMK_NO_MEMORY;
}
bmk_status reset(bmk_context *ctx,uint32_t kind) noexcept {
    if (!ctx || kind) return BMK_UNSUPPORTED;
    ctx->operation=nullptr;
    return BMK_OK;
}
bmk_status encode(bmk_context *ctx,const bmk_object_view *in,bmk_blob *out) noexcept {
    if (!ctx || !wire::empty(out)) return BMK_BAD_INPUT;
    ctx->operation=nullptr;
    wire::Input data;
    const auto rc=inspect(in,data);
    if (rc!=BMK_OK) return rc;
    // A one-byte payload marker makes the empty message unambiguous.
    const auto n=data.bytes+1;
    std::unique_ptr<uint8_t[]> p(new (std::nothrow) uint8_t[wire::header+data.schema_size+n]);
    if (!p) return BMK_NO_MEMORY;
    auto *payload=p.get()+wire::header+data.schema_size;
    *payload=0;
    if (data.bytes) std::memcpy(payload+1,data.values,data.bytes);
    const auto result=wire::encode_header(magic,data,n,n,std::move(p),out);
    if (result==BMK_OK) ctx->operation="encode";
    return result;
}
bmk_status decode(bmk_context *ctx,const uint8_t *p,uint64_t n,bmk_owned_object *out) noexcept {
    if (!ctx || !wire::empty(out)) return BMK_BAD_INPUT;
    ctx->operation=nullptr;
    wire::Frame frame;
    const auto rc=wire::read(magic,p,n,limit,frame);
    if (rc!=BMK_OK) return rc;
    if (frame.dtype!=BMK_I64 || !ms(frame.schema,frame.schema_size) ||
        frame.payload_size!=frame.bytes+1 || frame.payload[0]!=0) return BMK_CORRUPT;
    auto object=wire::allocate(frame);
    if (!object) return BMK_NO_MEMORY;
    if (frame.bytes) std::memcpy(object->buffer.get(),frame.payload+1,frame.bytes);
    wire::decoded(out,frame,std::move(object));
    ctx->operation="decode";
    return BMK_OK;
}
bmk_status info(bmk_context *ctx,bmk_blob *out) noexcept {
    if (!ctx || !ctx->operation) return BMK_BAD_INPUT;
    return wire::text(out,ctx->operation[0]=='e' ?
        "{\"backend\":\"raw-copy\",\"mode\":\"batch\",\"threads\":1,\"blocks\":1,\"operation\":\"encode\"}" :
        "{\"backend\":\"raw-copy\",\"mode\":\"batch\",\"threads\":1,\"blocks\":1,\"operation\":\"decode\"}");
}
bmk_status error(bmk_context *,char *out,uint64_t n) noexcept { return wire::error(out,n,"raw timestamp"); }
void destroy(bmk_context *p) noexcept { delete p; }
constexpr bmk_plugin_v1 api{sizeof(api),BMK_ABI_V1,identifier,probe,create,reset,encode,decode,info,error,destroy,wire::extension};
}
extern "C" __attribute__((visibility("default")))
const bmk_plugin_v1 *bmk_get_plugin(uint32_t v) { return v==BMK_ABI_V1 ? &api : nullptr; }
