#include "plugin_loader.hpp"

#include <algorithm>
#include <charconv>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {
constexpr uint64_t data_limit = 64 * UINT64_C(1024) * 1024;
constexpr uint64_t schema_limit = 65536;
constexpr size_t column_limit = 128;
constexpr uint64_t frame_limit = 2 * data_limit + schema_limit;

size_t dtype_width(uint32_t dtype) {
    switch (dtype) {
    case BMK_I8: case BMK_U8: case BMK_BOOL: return 1;
    case BMK_I16: case BMK_U16: case BMK_F16: return 2;
    case BMK_I32: case BMK_U32: case BMK_F32: return 4;
    case BMK_I64: case BMK_U64: case BMK_F64: return 8;
    default: throw tsbench::PluginError(BMK_UNSUPPORTED, "unknown dtype ID");
    }
}

uint32_t parse_dtype(std::string_view number) {
    uint32_t dtype = 0;
    const auto parse = std::from_chars(number.data(), number.data() + number.size(), dtype);
    if (parse.ec != std::errc{} || parse.ptr != number.data() + number.size())
        throw std::runtime_error("invalid numeric dtype ID");
    return dtype;
}

struct ExportedColumn { const uint8_t *data; size_t bytes; };
ExportedColumn exported(const bmk_array_view &col, uint64_t budget) {
    if (col.struct_size < sizeof(col) || col.rank != 1 || col.flags || col.validity ||
        col.validity_bytes || col.validity_bit_offset)
        throw tsbench::PluginError(BMK_INTERNAL, "worker cannot export decoded layout");
    const size_t width = dtype_width(col.dtype);
    if (col.shape[0] > budget / width || col.strides_bytes[0] != static_cast<int64_t>(width))
        throw tsbench::PluginError(BMK_INTERNAL, "invalid decoded element count or stride");
    const size_t bytes = col.shape[0] * width;
    if (col.origin_offset > col.storage_bytes || bytes > col.storage_bytes - col.origin_offset ||
        col.origin_offset > SIZE_MAX - bytes || (bytes && !col.storage))
        throw tsbench::PluginError(BMK_INTERNAL, "invalid decoded storage range");
    return {bytes ? static_cast<const uint8_t *>(col.storage) + col.origin_offset : nullptr, bytes};
}

std::vector<uint8_t> read_file(const char *path, uint64_t max_size) {
    if (!std::filesystem::is_regular_file(path)) throw std::runtime_error("input is not a regular file");
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    const auto n = file.tellg();
    if (n < 0) throw std::runtime_error("cannot size input file");
    if (static_cast<uint64_t>(n) > max_size) throw tsbench::PluginError(BMK_RESOURCE_LIMIT, "input exceeds bound");
    std::vector<uint8_t> bytes(static_cast<size_t>(n));
    file.seekg(0);
    if ((n && !file.read(reinterpret_cast<char *>(bytes.data()), n)) || file.peek() != EOF || file.bad())
        throw std::runtime_error("input read failed or size changed");
    return bytes;
}

void write_file(const char *path, const uint8_t *bytes, size_t n) {
    std::FILE *f = std::fopen(path, "wbx");
    if (!f) throw std::runtime_error("cannot exclusively create output file");
    const bool ok = !n || std::fwrite(bytes, 1, n, f) == n;
    if (std::fclose(f) != 0 || !ok) throw std::runtime_error("output write failed");
}

void write_info(const bmk_blob &info) {
    if (!info.size || info.size > schema_limit)
        throw tsbench::PluginError(BMK_INTERNAL, "invalid execution info length");
    std::cout.write(reinterpret_cast<const char *>(info.data), static_cast<std::streamsize>(info.size));
    std::cout << '\n';
}
}

int main(int argc, char **argv) {
    // This executable is an internal worker for pre-bound trusted builds. It
    // does not interpret the registry or claim standalone qualification.
    const std::string_view operation = argc > 1 ? argv[1] : "";
    const bool encode_columns = operation == "encode-columns", decode_columns = operation == "decode-columns";
    if (!((operation == "encode" && argc == 9) || (operation == "decode" && argc == 8) ||
          (encode_columns && argc >= 9 && (argc - 7) % 2 == 0 && (argc - 7) / 2 <= int(column_limit)) ||
          (decode_columns && argc >= 8 && argc - 7 <= int(column_limit)))) {
        std::cerr << "internal worker: encode LIB ID OPTIONS DTYPE DATA SCHEMA OUT | "
                     "decode LIB ID OPTIONS STREAM OUT_DATA OUT_SCHEMA | "
                     "encode-columns LIB ID OPTIONS SCHEMA OUT (DTYPE DATA)+ | "
                     "decode-columns LIB ID OPTIONS STREAM OUT_SCHEMA OUT_DATA+\n";
        return 2;
    }
    try {
#ifdef TSBENCH_LINKED_ENTRY
        const auto module = tsbench::PluginModule::from_linked(argv[2], argv[3], &bmk_get_plugin);
#else
        const auto module = tsbench::PluginModule::load(argv[2], argv[3]);
#endif
        const std::string_view options = argv[4];
        if (options.size() > schema_limit) throw tsbench::PluginError(BMK_RESOURCE_LIMIT, "options exceed bound");
        if (operation == "encode" || encode_columns) {
            const size_t count = encode_columns ? (argc - 7) / 2 : 1;
            std::vector<std::vector<uint8_t>> values(count);
            std::vector<bmk_array_view> columns(count);
            uint64_t remaining = data_limit;
            for (size_t i = 0; i < count; ++i) {
                const size_t at = encode_columns ? 7 + 2*i : 5;
                const uint32_t dtype = parse_dtype(argv[at]);
                const size_t width = dtype_width(dtype);
                values[i] = read_file(argv[at+1], remaining);
                const size_t bytes = values[i].size();
                if (bytes % width) throw std::runtime_error("misaligned input length");
                remaining -= bytes;
                auto &col = columns[i];
                col.struct_size = sizeof(col); col.dtype = dtype; col.rank = 1;
                col.storage = values[i].data(); col.storage_bytes = bytes;
                col.shape[0] = bytes / width; col.strides_bytes[0] = static_cast<int64_t>(width);
            }
            auto schema = read_file(argv[encode_columns ? 5 : 7], schema_limit);
            bmk_object_view input{sizeof(input), static_cast<uint32_t>(count), columns.data(), schema.data(), schema.size()};
            std::unique_ptr<tsbench::Blob> stream, info;
            {
                tsbench::Context ctx(module, options);
                stream = ctx.encode(input);
                info = ctx.execution_info();
            }
            if (stream->get().size > frame_limit) throw tsbench::PluginError(BMK_RESOURCE_LIMIT, "frame exceeds bound");
            write_file(argv[encode_columns ? 6 : 8], stream->get().data, stream->get().size);
            write_info(info->get());
        } else {
            auto stream = read_file(argv[5], frame_limit);
            std::unique_ptr<tsbench::Object> decoded;
            std::unique_ptr<tsbench::Blob> info;
            {
                tsbench::Context ctx(module, options);
                decoded = ctx.decode(stream.data(), stream.size());
                info = ctx.execution_info();
            }
            const auto &view = decoded->get();
            const size_t count = decode_columns ? argc - 7 : 1;
            if (view.column_count != count || !view.columns || view.schema_bytes > schema_limit)
                throw tsbench::PluginError(BMK_INTERNAL, "worker output column count or schema bound mismatch");
            std::vector<ExportedColumn> exports;
            uint64_t remaining = data_limit;
            for (size_t i = 0; i < count; ++i) {
                exports.push_back(exported(view.columns[i], remaining));
                remaining -= exports.back().bytes;
            }
            for (size_t i = 0; i < count; ++i)
                write_file(argv[decode_columns ? 7 + i : 6], exports[i].data, exports[i].bytes);
            write_file(argv[decode_columns ? 6 : 7], view.schema_json, view.schema_bytes);
            if (decode_columns) std::cout << "{\"columns\":[";
            for (size_t i = 0; i < count; ++i) {
                const auto &col = view.columns[i];
                if (i) std::cout << ',';
                std::cout << "{\"dtype\":" << col.dtype << ",\"count\":" << col.shape[0] << '}';
            }
            if (decode_columns) std::cout << "]}";
            std::cout << '\n';
            write_info(info->get());
        }
        return std::cout ? 0 : 2;
    } catch (const tsbench::PluginError &error) {
        std::cerr << "plugin status " << error.status() << ": " << error.what() << '\n';
        return 3;
    } catch (const std::exception &error) {
        std::cerr << "worker rejected: " << error.what() << '\n';
        return 2;
    }
}
