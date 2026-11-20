#include "plugin_loader.hpp"

#include <algorithm>
#include <cstring>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace {
constexpr uint64_t data_limit = 512 * UINT64_C(1024) * 1024;
constexpr uint64_t schema_limit = 65536;
constexpr uint64_t frame_limit = 768 * UINT64_C(1024) * 1024;

size_t dtype_width(uint32_t dtype) {
    switch (dtype) {
    case BMK_I8: case BMK_U8: case BMK_BOOL: return 1;
    case BMK_I16: case BMK_U16: case BMK_F16: return 2;
    case BMK_I32: case BMK_U32: case BMK_F32: return 4;
    case BMK_I64: case BMK_U64: case BMK_F64: return 8;
    default: throw tsbench::PluginError(BMK_UNSUPPORTED, "unknown dtype ID");
    }
}

std::vector<uint8_t> read_file(const char *path, uint64_t max_size) {
    if (!std::filesystem::is_regular_file(path)) throw std::runtime_error("input is not a regular file");
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    const auto n = file.tellg();
    if (n < 0 || static_cast<uint64_t>(n) > max_size)
        throw tsbench::PluginError(BMK_RESOURCE_LIMIT, "input exceeds bound");
    std::vector<uint8_t> bytes(static_cast<size_t>(n));
    file.seekg(0);
    if ((n && !file.read(reinterpret_cast<char *>(bytes.data()), n)) || file.peek() != EOF || file.bad())
        throw std::runtime_error("input read failed or size changed");
    return bytes;
}

void write_file(const std::filesystem::path &path, const uint8_t *bytes, size_t n) {
    std::ofstream file(path, std::ios::binary);
    if (!file || (n && !file.write(reinterpret_cast<const char *>(bytes), static_cast<std::streamsize>(n))))
        throw std::runtime_error("output write failed");
}

const uint8_t *decoded_bytes(const bmk_array_view &view, uint32_t dtype, size_t expected_bytes) {
    const size_t width = dtype_width(dtype);
    if (view.struct_size < sizeof(view) || view.dtype != dtype || view.rank != 1 || view.flags ||
        view.validity || view.validity_bytes || view.validity_bit_offset || view.strides_bytes[0] != static_cast<int64_t>(width) ||
        view.shape[0] != expected_bytes / width || view.origin_offset > view.storage_bytes ||
        expected_bytes > view.storage_bytes - view.origin_offset || (expected_bytes && !view.storage))
        throw tsbench::PluginError(BMK_INTERNAL, "decoded corpus layout differs");
    return expected_bytes ? static_cast<const uint8_t *>(view.storage) + view.origin_offset : nullptr;
}

std::string info(tsbench::Context &ctx) {
    const auto blob = ctx.execution_info();
    const auto &value = blob->get();
    if (!value.data || value.size == 0 || value.size > schema_limit)
        throw tsbench::PluginError(BMK_INTERNAL, "invalid execution info");
    return std::string(reinterpret_cast<const char *>(value.data), value.size);
}

int value_roundtrip(int argc, char **argv) {
    // value-roundtrip LIB ID OPTIONS SCHEMA OUT_DIR DTYPE DATA...
    if (argc < 9) return 2;
    const auto module = tsbench::PluginModule::load(argv[2], argv[3]);
    const std::string_view options = argv[4];
    const auto schema = read_file(argv[5], schema_limit);
    const std::filesystem::path output = argv[6];
    std::filesystem::create_directories(output);
    const uint32_t dtype = static_cast<uint32_t>(std::stoul(argv[7]));
    const size_t width = dtype_width(dtype);
    std::cout << "{\"columns\":[";
    for (int i = 8; i < argc; ++i) {
        const auto input = read_file(argv[i], data_limit);
        if (input.size() % width) throw tsbench::PluginError(BMK_BAD_INPUT, "misaligned corpus column");
        bmk_array_view column{};
        column.struct_size = sizeof(column); column.dtype = dtype; column.rank = 1;
        column.storage = input.data(); column.storage_bytes = input.size();
        column.shape[0] = input.size() / width; column.strides_bytes[0] = static_cast<int64_t>(width);
        bmk_object_view object{sizeof(object), 1, &column, schema.data(), schema.size()};
        tsbench::Context ctx(module, options);
        const auto encoded = ctx.encode(object);
        if (!encoded->get().data || encoded->get().size == 0 || encoded->get().size > frame_limit)
            throw tsbench::PluginError(BMK_INTERNAL, "invalid corpus encoded artifact");
        const auto decoded = ctx.decode(encoded->get().data, encoded->get().size);
        const auto &view = decoded->get();
        if (view.column_count != 1 || view.schema_bytes != schema.size() ||
            std::memcmp(view.schema_json, schema.data(), schema.size()) != 0)
            throw tsbench::PluginError(BMK_CORRUPT, "corpus schema did not roundtrip");
        const auto restored = decoded_bytes(view.columns[0], dtype, input.size());
        if (input.size() && std::memcmp(restored, input.data(), input.size()) != 0)
            throw tsbench::PluginError(BMK_CORRUPT, "corpus values did not roundtrip");
        const auto artifact = output / ("column-" + std::to_string(i - 8) + ".bmk");
        write_file(artifact, encoded->get().data, encoded->get().size);
        if (i != 8) std::cout << ',';
        std::cout << "{\"column\":" << (i - 8) << ",\"input_bytes\":" << input.size()
                  << ",\"artifact_bytes\":" << encoded->get().size << ",\"execution_info\":" << info(ctx) << '}';
    }
    std::cout << "]}\n";
    return 0;
}

int bytes_roundtrip(int argc, char **argv) {
    // bytes-roundtrip LIB ID OPTIONS SCHEMA OUT_FRAME DATA
    if (argc != 8) return 2;
    const auto module = tsbench::PluginModule::load(argv[2], argv[3]);
    const auto options = std::string_view(argv[4]);
    const auto schema = read_file(argv[5], schema_limit);
    const auto input = read_file(argv[7], data_limit);
    bmk_array_view column{};
    column.struct_size = sizeof(column); column.dtype = BMK_U8; column.rank = 1;
    column.storage = input.data(); column.storage_bytes = input.size();
    column.shape[0] = input.size(); column.strides_bytes[0] = 1;
    bmk_object_view object{sizeof(object), 1, &column, schema.data(), schema.size()};
    tsbench::Context ctx(module, options);
    const auto encoded = ctx.encode(object);
    if (!encoded->get().data || encoded->get().size == 0 || encoded->get().size > frame_limit)
        throw tsbench::PluginError(BMK_INTERNAL, "invalid corpus byte artifact");
    const auto decoded = ctx.decode(encoded->get().data, encoded->get().size);
    const auto &view = decoded->get();
    if (view.column_count != 1 || view.schema_bytes != schema.size() ||
        std::memcmp(view.schema_json, schema.data(), schema.size()) != 0)
        throw tsbench::PluginError(BMK_CORRUPT, "corpus byte schema did not roundtrip");
    const auto restored = decoded_bytes(view.columns[0], BMK_U8, input.size());
    if (input.size() && std::memcmp(restored, input.data(), input.size()) != 0)
        throw tsbench::PluginError(BMK_CORRUPT, "corpus bytes did not roundtrip");
    const std::filesystem::path output(argv[6]);
    if (output.has_parent_path()) std::filesystem::create_directories(output.parent_path());
    write_file(output, encoded->get().data, encoded->get().size);
    std::cout << "{\"input_bytes\":" << input.size() << ",\"artifact_bytes\":" << encoded->get().size
              << ",\"execution_info\":" << info(ctx) << "}\n";
    return 0;
}
}

int main(int argc, char **argv) {
    const std::string_view operation = argc > 1 ? argv[1] : "";
    try {
        if (operation == "value-roundtrip") return value_roundtrip(argc, argv);
        if (operation == "bytes-roundtrip") return bytes_roundtrip(argc, argv);
        std::cerr << "corpus worker: value-roundtrip LIB ID OPTIONS SCHEMA OUT_DIR DTYPE DATA... | "
                     "bytes-roundtrip LIB ID OPTIONS SCHEMA OUT_FRAME DATA\n";
        return 2;
    } catch (const tsbench::PluginError &error) {
        std::cerr << "plugin status " << error.status() << ": " << error.what() << '\n';
        return 3;
    } catch (const std::exception &error) {
        std::cerr << "corpus worker rejected: " << error.what() << '\n';
        return 2;
    }
}
