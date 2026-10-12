#include "deepzip/deepzip.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

static deepzip::Bytes read(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot read " + path);
    return deepzip::Bytes(std::istreambuf_iterator<char>(input), {});
}

template<class T> static void write(const std::string& path, const std::vector<T>& values) {
    std::ofstream output(path, std::ios::binary);
    if (!output) throw std::runtime_error("cannot write " + path);
    for (const T& value : values) {
        unsigned char bytes[sizeof(T)];
        std::memcpy(bytes, &value, sizeof(T));
        const std::uint16_t endian = 1;
        if (*reinterpret_cast<const unsigned char*>(&endian) != 1)
            throw std::runtime_error("little-endian diagnostic host required");
        output.write(reinterpret_cast<const char*>(bytes), sizeof(T));
    }
    if (!output) throw std::runtime_error("write failed");
}

int main(int argc, char** argv) {
    try {
        if (argc != 6) throw std::runtime_error("model contexts source-probabilities output-prefix maps-path");
        const auto model = deepzip::Model::load(read(argv[1]));
        const auto raw = read(argv[2]);
        if (raw.size() != 3 * 64 * 4 || model.alphabet_size() != 4 || model.name() != "biGRU")
            throw std::runtime_error("frozen case dimensions changed");
        std::vector<std::uint32_t> contexts;
        for (std::size_t i=0; i<raw.size(); i+=4)
            contexts.push_back(raw[i] | (std::uint32_t(raw[i+1])<<8) |
                               (std::uint32_t(raw[i+2])<<16) | (std::uint32_t(raw[i+3])<<24));
        const auto probabilities = model.predict(contexts, deepzip::Backend::scalar);
        const auto source_raw = read(argv[3]);
        if (probabilities.size() != 12 || source_raw.size() != 48)
            throw std::runtime_error("probability output count mismatch");
        std::vector<float> source(12);
        std::memcpy(source.data(), source_raw.data(), source_raw.size());
        std::vector<std::uint64_t> native_cdf, source_cdf;
        for (std::size_t row=0; row<3; ++row) {
            auto table = deepzip::cumulative(std::vector<float>(probabilities.begin()+row*4, probabilities.begin()+(row+1)*4));
            native_cdf.insert(native_cdf.end(), table.begin(), table.end());
            table = deepzip::cumulative(std::vector<float>(source.begin()+row*4, source.begin()+(row+1)*4));
            source_cdf.insert(source_cdf.end(), table.begin(), table.end());
        }
        const std::string prefix = argv[4];
        write(prefix + ".probabilities.f32", probabilities);
        write(prefix + ".cumulative.u64", native_cdf);
        write(prefix + ".source-probability-cumulative.u64", source_cdf);
        std::ifstream maps("/proc/self/maps");
        std::ofstream maps_out(argv[5]);
        maps_out << maps.rdbuf();
        if (!maps_out) throw std::runtime_error("maps write failed");
        std::cout << "fixed 3 x 4 scalar prediction and both CDF conversions completed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
