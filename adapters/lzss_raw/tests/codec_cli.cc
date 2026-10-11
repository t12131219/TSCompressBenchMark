#include "tscb_adapter_v1.h"
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

static tscb_buffer_v1 view(std::vector<unsigned char>& bytes, size_t capacity, size_t used) {
    tscb_buffer_v1 buffer{};
    buffer.data = bytes.data();
    buffer.capacity_bytes = capacity;
    buffer.used_bytes = used;
    buffer.dtype = TSCB_DTYPE_BYTES_V1;
    buffer.rank = 1;
    buffer.shape[0] = used;
    buffer.strides_bytes[0] = 1;
    return buffer;
}

int main(int argc, char** argv) {
    tscb_codec_handle_v1* handle = nullptr;
    try {
        const bool encode = argc == 4 && std::string(argv[1]) == "encode";
        const bool decode = argc == 5 && std::string(argv[1]) == "decode";
        if (!encode && !decode) throw std::runtime_error("encode input output | decode input length output");
        std::ifstream input_file(argv[2], std::ios::binary);
        if (!input_file) throw std::runtime_error("input open failed");
        std::vector<unsigned char> source((std::istreambuf_iterator<char>(input_file)), {});
        const size_t length = source.size();
        if (length > UINT32_MAX) throw std::runtime_error("input too large");
        source.resize(std::max<size_t>(1, length));
        auto input = view(source, length, length);
        const char config[] = "{\"ei\":10,\"ej\":4,\"initial_byte\":32}";
        if (tscb_create(config, sizeof(config) - 1, &handle)) throw std::runtime_error("create failed");
        uint64_t capacity = 0;
        if (encode) {
            if (tscb_compress_bound(handle, &input, &capacity)) throw std::runtime_error("bound failed");
        } else {
            char* end = nullptr;
            errno = 0;
            capacity = std::strtoull(argv[3], &end, 10);
            if (errno || !*argv[3] || *end || *argv[3] == '-' || capacity > UINT32_MAX)
                throw std::runtime_error("invalid expected length");
        }
        std::vector<unsigned char> destination(static_cast<size_t>(capacity) + 16, 0xCA);
        auto output = view(destination, static_cast<size_t>(capacity), 0);
        const auto status = encode ? tscb_compress(handle, &input, &output)
                                   : tscb_decompress(handle, &input, &output);
        if (status) throw std::runtime_error("codec returned " + std::to_string(status));
        const size_t written = static_cast<size_t>(output.used_bytes);
        if (written > capacity || !std::all_of(destination.begin() + capacity, destination.end(),
                                              [](unsigned char value) { return value == 0xCA; }))
            throw std::runtime_error("capacity guard changed");
        if (encode && (tscb_finalize(handle, &output) || output.used_bytes != 0))
            throw std::runtime_error("finalize failed");
        std::ofstream output_file(argv[encode ? 3 : 4], std::ios::binary);
        output_file.write(reinterpret_cast<const char*>(destination.data()), static_cast<std::streamsize>(written));
        if (!output_file) throw std::runtime_error("output write failed");
        tscb_destroy(handle);
        return 0;
    } catch (const std::exception& error) {
        tscb_destroy(handle);
        std::cerr << error.what() << '\n';
        return 1;
    }
}
