#include "plugin_loader.hpp"

#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace tsbench;
namespace {
void check(bool result, const char *message) { if (!result) throw std::runtime_error(message); }
template <typename F> void rejects(F action, bmk_status status) {
    try { action(); } catch (const PluginError &e) {
        check(e.status() == status, e.what());
        return;
    }
    throw std::runtime_error("expected plugin error");
}
}

int main(int argc, char **argv) {
    try {
        check(argc == 7, "expected module paths");
        rejects([&] { PluginModule::load("relative.so", "raw-store"); }, BMK_BAD_INPUT);
        rejects([&] { PluginModule::load(argv[6], "invalid"); }, BMK_UNSUPPORTED); // not ELF
        for (int i = 2; i < argc - 1; ++i)
            rejects([&] { PluginModule::load(argv[i], "invalid"); }, BMK_UNSUPPORTED);
        rejects([&] { PluginModule::load(argv[1], "unrelated"); }, BMK_BAD_INPUT);
        auto module = PluginModule::load(argv[1], "raw-store");
        std::weak_ptr<const PluginModule> weak = module;
        for (const auto *s : {"", "null", "{\"x\":0,\"x\":1}", "{\"threads\":2}", "{} {}"})
            rejects([&] { Context ctx(module, s); }, BMK_BAD_OPTIONS);

        std::array<uint64_t, 5> f64{0, 0x8000000000000000, 0x7ff8000000000001, 0xfff80000000000ff, 1};
        std::string schema = R"({"dtype":"f64","name":"V","rank":1,"role":"value"})";
        bmk_array_view col{};
        col.struct_size = sizeof(col); col.dtype = BMK_F64; col.rank = 1;
        col.storage = f64.data(); col.storage_bytes = sizeof(f64); col.origin_offset = sizeof(uint64_t);
        col.shape[0] = f64.size()-1; col.strides_bytes[0] = sizeof(uint64_t);
        bmk_object_view input{sizeof(input), 1, &col, reinterpret_cast<const uint8_t *>(schema.data()), schema.size()};
        check(Context::probe(module, input, "{ }\n")->get().size != 0, "empty probe result");
        col.strides_bytes[0] = -8;
        rejects([&] { Context::probe(module, input, "{}"); }, BMK_UNSUPPORTED);
        col.strides_bytes[0] = 8; col.shape[0] = UINT64_MAX;
        rejects([&] { Context::probe(module, input, "{}"); }, BMK_RESOURCE_LIMIT);
        col.shape[0] = f64.size();
        rejects([&] { Context::probe(module, input, "{}"); }, BMK_BAD_INPUT);
        col.shape[0] -= 1;
        std::unique_ptr<Blob> frame;
        {
            Context encoder(module, "{}");
            frame = encoder.encode(input);
            check(frame->get().size == 24 + schema.size() + sizeof(f64) - sizeof(uint64_t), "wrong frame size");
            check(encoder.execution_info()->get().size > 0, "missing execution evidence");
            encoder.reset(0);
        }
        {
            Context decoder(module, "{}");
            rejects([&] { decoder.decode(frame->get().data, frame->get().size - 1); }, BMK_CORRUPT);
            rejects([&] { decoder.decode(frame->get().data, frame->get().size); }, BMK_BAD_INPUT);
        }
        std::unique_ptr<Object> object;
        {
            Context decoder(module, "{}");
            object = decoder.decode(frame->get().data, frame->get().size);
        }
        module.reset();
        frame.reset();
        check(!weak.expired(), "decoded result did not pin producing module");
        const auto &view = object->get();
        check(view.column_count == 1 && view.schema_bytes == schema.size() &&
              std::memcmp(view.schema_json, schema.data(), schema.size()) == 0, "invalid restored schema");
        const auto &result = view.columns[0];
        check(result.dtype == BMK_F64 && result.shape[0] == f64.size()-1 &&
              result.storage_bytes == (f64.size()-1) * sizeof(uint64_t) &&
              std::memcmp(result.storage, f64.data()+1, result.storage_bytes) == 0, "loss of original bits");
        object.reset();
        check(weak.expired(), "module was not released");
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
