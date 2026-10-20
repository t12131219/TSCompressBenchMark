// Intrinsic complete codec frames, concatenated when the requested block size
// requires several independent blocks. Each intrinsic header delimits its frame.
#include "tsbench_core.hpp"
#include <memory>
#if TSCB_REWRITE_KIND == 3
namespace elf_plus { Encoded compress_unchecked(const uint8_t*, size_t, Width); }
#elif TSCB_REWRITE_KIND == 6
namespace elf_vldb { Encoded compress_unchecked(const uint8_t*, size_t, Width); }
#endif
namespace {
struct RewriteCore : tsbench_core::State {
    size_t count{}, bytes{}, width{}, block{1000}; bool decoder{};
};
[[maybe_unused]] size_t core_block_bound(size_t count, size_t width) {
#if TSCB_REWRITE_KIND == 3
    return elf_plus::compress_bound(count, static_cast<elf_plus::Width>(width * 8));
#elif TSCB_REWRITE_KIND == 6
    return elf_vldb::compress_bound(count, static_cast<elf_vldb::Width>(width * 8));
#elif TSCB_REWRITE_KIND == 7
    return elf_star::compress_bound(count, static_cast<elf_star::Width>(width * 8));
#else
    return tsbench_core::add(32 + 512, tsbench_core::multiply(count * width, 4));
#endif
}
[[maybe_unused]] Bytes core_block_encode(const uint8_t* input, size_t count, size_t width) {
#if TSCB_REWRITE_KIND == 3
    return elf_plus::compress_unchecked(input, count, static_cast<elf_plus::Width>(width * 8)).bytes;
#elif TSCB_REWRITE_KIND == 6
    return elf_vldb::compress_unchecked(input, count, static_cast<elf_vldb::Width>(width * 8)).bytes;
#elif TSCB_REWRITE_KIND == 7
    return elf_star::compress(input, count, static_cast<elf_star::Width>(width * 8)).bytes;
#else
    (void)input; (void)count; (void)width; return {};
#endif
}
[[maybe_unused]] Bytes core_block_decode(const uint8_t* input, size_t length, size_t width) {
#if TSCB_REWRITE_KIND == 3
    auto decoded = elf_plus::decompress(input, length);
#elif TSCB_REWRITE_KIND == 6
    auto decoded = elf_vldb::decompress(input, length);
#elif TSCB_REWRITE_KIND == 7
    auto decoded = elf_star::decompress(input, length);
#else
    (void)input; (void)length; (void)width; return {};
#endif
#if TSCB_REWRITE_KIND != 4
    tsbench_core::require(static_cast<unsigned>(decoded.width) == width * 8 && decoded.values.size() == decoded.count * width,
                          "intrinsic floating frame geometry mismatch");
    return std::move(decoded.values);
#endif
}
}
EXPORT uint32_t tsbench_core_version() { return 1; }
EXPORT uint32_t tsbench_core_storage() { return 0; }
EXPORT int tsbench_core_create(const tsbench_core_config* config, int decoder, void** result) {
    return tsbench_core::guard(nullptr, [&] {
        tsbench_core::require(config && result, "null floating core configuration"); *result = nullptr;
        if (config->dtype != TSCB_DTYPE_F32_LE_V1 && config->dtype != TSCB_DTYPE_F64_LE_V1)
            throw tsbench_core::Unsupported("floating rewrite requires float32 or float64");
        auto state = std::make_unique<RewriteCore>();
        state->count = tsbench_core::elements(*config); state->bytes = tsbench_core::input_bytes(*config);
        state->width = tsbench_core::width(config->dtype); state->decoder = decoder != 0;
        if (state->count > max_elements) throw tsbench_core::Unsupported("floating rewrite element limit");
        if (!decoder) {
            tsbench_core::Parameters parameters(config->parameters_json);
            if (parameters.contains("block_size")) state->block = parameters.integer("block_size", 1, 65535);
            if (parameters.contains("isa") && parameters.string("isa") != "SCALAR")
                throw tsbench_core::Unsupported("floating rewrite requires SCALAR");
#if TSCB_REWRITE_KIND == 4
            if (state->block > 16384 || (state->count + state->block - 1) / state->block > 1024 || state->bytes > 16777216)
                throw tsbench_core::Unsupported("SElfStar intrinsic session limits exceeded");
#elif TSCB_REWRITE_KIND == 6
            if (state->block > 16384) throw tsbench_core::Unsupported("Elf source block limit exceeded");
#elif TSCB_REWRITE_KIND == 7
            if (state->block > (state->width == 4 ? 1000u : 16384u))
                throw tsbench_core::Unsupported("ElfStar source block limit exceeded");
#endif
        }
        *result = state.release();
    });
}
EXPORT int tsbench_core_destroy(void* context) { delete static_cast<RewriteCore*>(context); return 0; }
EXPORT int tsbench_core_bound(void* context, const uint8_t* input, size_t length, size_t* bound) {
    auto* state = static_cast<RewriteCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && bound && (!length || input) && length == state->bytes, "floating input size mismatch");
#if TSCB_REWRITE_KIND == 4
        *bound = tsbench_core::add(32, tsbench_core::add(tsbench_core::multiply((state->count + state->block - 1) / state->block, 512),
                                                      tsbench_core::multiply(length, 4)));
#else
        *bound = 0;
        for (size_t position = 0; position < state->count; position += state->block)
            *bound = tsbench_core::add(*bound, core_block_bound(std::min(state->block, state->count - position), state->width));
        if (!state->count) *bound = core_block_bound(0, state->width);
#endif
    });
}
EXPORT int tsbench_core_encode(void* context, const uint8_t* input, size_t length,
                               uint8_t*, size_t, tsbench_core_result* result) {
    auto* state = static_cast<RewriteCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && !state->decoder && result && (!length || input) && length == state->bytes,
                              "floating direct input mismatch");
        Bytes encoded;
        try {
#if TSCB_REWRITE_KIND == 4
            self_star::Session session; session.width = static_cast<self_star::Width>(state->width * 8);
            for (size_t position = 0; position < state->count; position += state->block) {
                const size_t count = std::min(state->block, state->count - position);
                session.blocks.emplace_back(input + position * state->width, input + (position + count) * state->width);
            }
            encoded = self_star::compress(session).bytes;
#else
            if (state->count <= state->block) encoded = core_block_encode(input, state->count, state->width);
            else for (size_t position = 0; position < state->count; position += state->block) {
                auto frame = core_block_encode(input + position * state->width, std::min(state->block, state->count - position), state->width);
                encoded.insert(encoded.end(), frame.begin(), frame.end());
            }
#endif
        } catch (const std::invalid_argument& error) {
            // Frozen source domain rejections remain explicit; no raw fallback.
            throw tsbench_core::Unsupported(error.what());
        }
        tsbench_core::vector_result(std::move(encoded), result);
    });
}
EXPORT int tsbench_core_decode(void* context, const uint8_t* input, size_t length,
                               uint8_t*, size_t, tsbench_core_result* result) {
    auto* state = static_cast<RewriteCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && state->decoder && input && result, "invalid floating decode arguments");
        Bytes decoded;
#if TSCB_REWRITE_KIND == 4
        auto session = self_star::decompress(input, length);
        tsbench_core::require(!session.network && static_cast<unsigned>(session.width) == state->width * 8, "SElfStar session identity mismatch");
        if (session.blocks.size() == 1) decoded = std::move(session.blocks[0]);
        else for (auto& block : session.blocks) {
            tsbench_core::require(block.size() <= state->bytes - decoded.size(), "SElfStar output exceeds task");
            decoded.insert(decoded.end(), block.begin(), block.end());
        }
#else
        size_t position = 0;
        while (position < length) {
            constexpr size_t header_size = 32;
            constexpr size_t size_offset = 16;
            tsbench_core::require(length - position >= header_size, "truncated intrinsic floating header");
            const uint64_t payload = load(input + position + size_offset, 8);
            tsbench_core::require(payload <= length - position - header_size, "truncated intrinsic floating payload");
            const size_t frame_size = header_size + static_cast<size_t>(payload);
            auto block = core_block_decode(input + position, frame_size, state->width);
            tsbench_core::require(block.size() <= state->bytes - decoded.size(), "floating output exceeds task");
            if (position == 0 && frame_size == length) decoded = std::move(block);
            else decoded.insert(decoded.end(), block.begin(), block.end());
            position += frame_size;
        }
#endif
        tsbench_core::require(decoded.size() == state->bytes, "floating decoded size mismatch");
        tsbench_core::vector_result(std::move(decoded), result);
    });
}
EXPORT void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
EXPORT const char* tsbench_core_error(void* context) {
    return context ? static_cast<RewriteCore*>(context)->error.c_str() : tsbench_core::last_error().c_str();
}
