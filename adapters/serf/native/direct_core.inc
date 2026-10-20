#include "tsbench_core.hpp"
namespace {
struct SerfCore : tsbench_core::State {
    size_t count{}, bytes{}, width{};
    uint32_t block{1000}; double bound{0.001}; int64_t adjust{}; bool decoder{};
};
}
extern "C" uint32_t tsbench_core_version() { return 1; }
extern "C" uint32_t tsbench_core_storage() { return 2; }
extern "C" int tsbench_core_create(const tsbench_core_config* config, int decoder, void** result) {
    return tsbench_core::guard(nullptr, [&] {
        tsbench_core::require(config && result, "null Serf core configuration"); *result = nullptr;
        if (config->dtype != TSCB_DTYPE_F32_LE_V1 && config->dtype != TSCB_DTYPE_F64_LE_V1)
            throw tsbench_core::Unsupported("Serf requires float32 or float64");
        auto state = std::make_unique<SerfCore>();
        state->count = tsbench_core::elements(*config); state->bytes = tsbench_core::input_bytes(*config);
        state->width = tsbench_core::width(config->dtype); state->decoder = decoder != 0;
        if (state->count > kMaxElements) throw tsbench_core::Unsupported("Serf element limit");
        if (!decoder) {
            tsbench_core::Parameters parameters(config->parameters_json);
            if (parameters.contains("isa") && parameters.string("isa") != "SCALAR")
                throw tsbench_core::Unsupported("Serf requires SCALAR");
            if (parameters.contains("error_bound_type") && parameters.string("error_bound_type") != "ABSOLUTE")
                throw tsbench_core::Unsupported("Serf requires an absolute bound");
            if (parameters.contains("block_size")) state->block = parameters.integer("block_size", 1, kMaxBlockSize);
            if (parameters.contains("error_bound")) state->bound = parameters.real("error_bound");
            if (parameters.contains("adjust_digit")) state->adjust = parameters.integer("adjust_digit", -1000000000, 1000000000);
            if (state->bound <= 0 || (state->width == 4 && state->adjust != 0))
                throw tsbench_core::Unsupported("Serf bound or float32 adjustment unsupported");
            if (state->width == 4 && (!std::isfinite(static_cast<float>(state->bound)) ||
                                     std::nextafter(static_cast<float>(state->bound), 0.0f) <= 0))
                throw tsbench_core::Unsupported("Serf bound is not representable as float32");
        }
        *result = state.release();
    });
}
extern "C" int tsbench_core_destroy(void* context) { delete static_cast<SerfCore*>(context); return 0; }
extern "C" int tsbench_core_bound(void* context, const uint8_t* input, size_t length, size_t* bound) {
    auto* state = static_cast<SerfCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && bound && (!length || input) && length == state->bytes, "Serf input size mismatch");
        const size_t blocks = (state->count + state->block - 1) / state->block;
        *bound = tsbench_core::add(128, tsbench_core::add(tsbench_core::multiply(blocks, 24), tsbench_core::multiply(length, 4)));
    });
}
extern "C" int tsbench_core_encode(void* context, const uint8_t* input, size_t length,
                                    uint8_t*, size_t, tsbench_core_result* result) {
    auto* state = static_cast<SerfCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && !state->decoder && result && (!length || input) && length == state->bytes,
                              "Serf direct input mismatch");
        const InputView view{static_cast<uint8_t>(state->width), 1, state->block, state->count,
                             state->bound, state->adjust, input};
        Writer writer; uint64_t exceptions = 0;
        const bool ok = state->width == 4 ? encode_typed<float>(view, writer, exceptions, false)
                                          : encode_typed<double>(view, writer, exceptions, false);
        tsbench_core::require(ok, "Serf encoder produced an invalid block");
        tsbench_core::vector_result(std::move(writer.bytes), result);
    });
}
extern "C" int tsbench_core_decode(void* context, const uint8_t* input, size_t length,
                                    uint8_t* output, size_t capacity, tsbench_core_result* result) {
    auto* state = static_cast<SerfCore*>(context);
    return tsbench_core::guard(state, [&] {
        tsbench_core::require(state && state->decoder && input && result && length >= 48, "truncated Serf direct frame");
        Reader reader{input, length}; FrameInfo frame;
        tsbench_core::require(parse_frame_header(reader, frame, false) && frame.width == state->width &&
                              frame.columns == 1 && frame.rows == state->count, "Serf frame geometry mismatch");
        if (capacity < state->bytes) throw tsbench_core::Capacity("Serf decoded buffer too small");
        tsbench_core::require(output || !state->bytes, "null Serf decoded buffer");
        const bool ok = frame.width == 4 ? decode_typed<float>(reader, frame, output, state->bytes)
                                         : decode_typed<double>(reader, frame, output, state->bytes);
        tsbench_core::require(ok && reader.offset == reader.size, "malformed Serf direct records");
        tsbench_core::caller_result(output, state->bytes, capacity, result);
    });
}
extern "C" void tsbench_core_release(tsbench_core_result* result) { tsbench_core::release(result); }
extern "C" const char* tsbench_core_error(void* context) {
    return context ? static_cast<SerfCore*>(context)->error.c_str() : tsbench_core::last_error().c_str();
}
