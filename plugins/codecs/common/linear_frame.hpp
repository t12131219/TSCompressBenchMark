#pragma once
#include "tsbench/plugin_abi.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include <string_view>

namespace tsbench::linear {
constexpr size_t header = 32;
constexpr size_t schema_limit = 65536;
constexpr size_t logical_limit = 64 * 1024 * 1024;
using Magic = std::array<uint8_t, 8>;

inline unsigned width(uint32_t type) noexcept {
    switch (type) {
    case BMK_I8: case BMK_U8: case BMK_BOOL: return 1;
    case BMK_I16: case BMK_U16: case BMK_F16: return 2;
    case BMK_I32: case BMK_U32: case BMK_F32: return 4;
    case BMK_I64: case BMK_U64: case BMK_F64: return 8;
    default: return 0;
    }
}

// Initial per-plugin schemas are an empty object or one closed ASCII enum.
// Control-layer JSON is canonical. At the ABI, accept JSON whitespace and
// reject unknown/duplicate keys, noncanonical enum spellings and trailing text.
class Options {
public:
    Options(const uint8_t *p, uint64_t n) : rest_(p && n <= schema_limit ?
        std::string_view(reinterpret_cast<const char *>(p), static_cast<size_t>(n)) : std::string_view{}) {}
    bool token(std::string_view literal) noexcept {
        spaces();
        if (rest_.substr(0, literal.size()) != literal) return false;
        rest_.remove_prefix(literal.size());
        return true;
    }
    bool done() noexcept { spaces(); return rest_.empty(); }
private:
    void spaces() noexcept {
        const auto first = rest_.find_first_not_of(" \n\t\r");
        rest_.remove_prefix(first == std::string_view::npos ? rest_.size() : first);
    }
    std::string_view rest_;
};

struct Input {
    uint32_t dtype{};
    size_t count{}, bytes{}, schema_size{};
    const uint8_t *values{}, *schema{};
};
inline bmk_status view(const bmk_object_view *object, size_t limit, Input &out) noexcept {
    if (!object || object->struct_size < sizeof(*object)) return BMK_BAD_INPUT;
    if (object->column_count != 1) return BMK_UNSUPPORTED;
    const auto *col = object->columns;
    if (!col || col->struct_size < sizeof(*col)) return BMK_BAD_INPUT;
    const unsigned stride = width(col->dtype);
    if (!stride || col->rank != 1 || col->flags || col->validity || col->validity_bytes ||
        col->validity_bit_offset || col->strides_bytes[0] != stride) return BMK_UNSUPPORTED;
    if (col->shape[0] > limit / stride || object->schema_bytes > schema_limit) return BMK_RESOURCE_LIMIT;
    const size_t bytes = static_cast<size_t>(col->shape[0]) * stride;
    if (col->origin_offset > col->storage_bytes || bytes > col->storage_bytes - col->origin_offset ||
        col->origin_offset > SIZE_MAX - bytes || (bytes && !col->storage) ||
        (object->schema_bytes && !object->schema_json)) return BMK_BAD_INPUT;
    out = {col->dtype, static_cast<size_t>(col->shape[0]), bytes, static_cast<size_t>(object->schema_bytes),
           bytes ? static_cast<const uint8_t *>(col->storage) + col->origin_offset : nullptr,
           object->schema_json};
    return BMK_OK;
}

inline void put(uint8_t *out, unsigned n, uint64_t word) noexcept {
    for (unsigned i = 0; i < n; ++i) out[i] = static_cast<uint8_t>(word >> (8*i));
}
inline uint64_t get(const uint8_t *in, unsigned n) noexcept {
    uint64_t word = 0;
    for (unsigned i = 0; i < n; ++i) word |= uint64_t(in[i]) << (8*i);
    return word;
}
struct Frame {
    uint32_t dtype{};
    size_t count{}, bytes{}, schema_size{}, payload_size{};
    const uint8_t *schema{}, *payload{};
};
inline bmk_status read(const Magic &magic, const uint8_t *p, uint64_t n, size_t limit, Frame &f) noexcept {
    if (!p || n < header || std::memcmp(magic.data(), p, magic.size())) return BMK_CORRUPT;
    const auto dtype = static_cast<uint32_t>(get(p+8, 4));
    const uint64_t count = get(p+12, 8), schema = get(p+20, 4), length = get(p+24, 8);
    const unsigned item = width(dtype);
    if (!item || schema > n-header || length != n-header-schema || !length || length > SIZE_MAX) return BMK_CORRUPT;
    if (count > limit / item || schema > schema_limit) return BMK_RESOURCE_LIMIT;
    f = {dtype, static_cast<size_t>(count), static_cast<size_t>(count)*item, static_cast<size_t>(schema),
         static_cast<size_t>(length), p+header, p+header+schema};
    return BMK_OK;
}

inline bool empty(const bmk_blob *out) noexcept {
    return out && out->struct_size >= sizeof(*out) && !out->owner && !out->release;
}
inline bool empty(const bmk_owned_object *out) noexcept {
    return out && out->struct_size >= sizeof(*out) && !out->owner && !out->release;
}
inline void release_blob(bmk_blob *blob) noexcept {
    delete[] static_cast<uint8_t *>(blob->owner);
    *blob = {}; blob->struct_size = sizeof(*blob);
}
inline void blob(bmk_blob *out, std::unique_ptr<uint8_t[]> data, size_t size, size_t capacity) noexcept {
    auto *p = data.release();
    *out = {sizeof(*out), 0, p, size, capacity, p, release_blob};
}
inline bmk_status text(bmk_blob *out, std::string_view message) noexcept {
    if (!empty(out)) return BMK_BAD_INPUT;
    std::unique_ptr<uint8_t[]> data(new (std::nothrow) uint8_t[message.size()]);
    if (!data) return BMK_NO_MEMORY;
    std::memcpy(data.get(), message.data(), message.size());
    blob(out, std::move(data), message.size(), message.size());
    return BMK_OK;
}
inline bmk_status encode_header(const Magic &magic, const Input &input, size_t bound, size_t used,
        std::unique_ptr<uint8_t[]> buffer, bmk_blob *out) noexcept {
    if (!used || used > bound) return BMK_INTERNAL;
    auto *p = buffer.get();
    std::memcpy(p, magic.data(), magic.size());
    put(p+8, 4, input.dtype); put(p+12, 8, input.count);
    put(p+20, 4, input.schema_size); put(p+24, 8, used);
    if (input.schema_size) std::memcpy(p+header, input.schema, input.schema_size);
    blob(out, std::move(buffer), header + input.schema_size + used, header + input.schema_size + bound);
    return BMK_OK;
}

struct Object {
    bmk_array_view column{};
    std::unique_ptr<uint8_t[]> buffer;
};
inline std::unique_ptr<Object> allocate(const Frame &frame) noexcept {
    std::unique_ptr<Object> object(new (std::nothrow) Object);
    if (!object) return {};
    if (frame.bytes || frame.schema_size) {
        object->buffer.reset(new (std::nothrow) uint8_t[frame.bytes+frame.schema_size]);
        if (!object->buffer) return {};
    }
    auto &col = object->column;
    col.struct_size = sizeof(col); col.dtype = frame.dtype; col.rank = 1;
    col.storage = frame.bytes ? object->buffer.get() : nullptr; col.storage_bytes = frame.bytes;
    col.shape[0] = frame.count; col.strides_bytes[0] = width(frame.dtype);
    return object;
}
inline void release_object(bmk_owned_object *out) noexcept {
    delete static_cast<Object *>(out->owner);
    *out = {}; out->struct_size = sizeof(*out);
}
inline void decoded(bmk_owned_object *out, const Frame &frame, std::unique_ptr<Object> object) noexcept {
    auto *o = object.release();
    auto *schema = frame.schema_size ? o->buffer.get()+frame.bytes : nullptr;
    if (schema) std::memcpy(schema, frame.schema, frame.schema_size);
    *out = {sizeof(*out), 0, {sizeof(bmk_object_view), 1, &o->column, schema, frame.schema_size}, o, release_object};
}
inline bmk_status error(char *out, uint64_t capacity, const char *reason) noexcept {
    if (!out || !capacity) return BMK_BAD_INPUT;
    const auto n = std::min<uint64_t>(capacity-1, std::strlen(reason));
    std::memcpy(out, reason, static_cast<size_t>(n)); out[n] = 0;
    return BMK_OK;
}
inline const void *extension(const char *, uint32_t) noexcept { return nullptr; }
inline bool valid_host(const bmk_host_v1 *host) noexcept {
    return host && host->struct_size >= sizeof(*host) && host->abi_version == BMK_ABI_V1;
}
} // namespace tsbench::linear
