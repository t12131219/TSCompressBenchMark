// Direct, source-side control. No TSBench ABI and no ISA-targeted calls before the host guard.
#include "native_profile.hpp"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace tsbench::sprintz_fire;

void require(bool value, const char *message) {
    if (!value) throw std::logic_error(message);
}

sf::Bytes read(const char *path, size_t limit) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    require(in.good(), "open input");
    const auto size = in.tellg();
    require(size >= 0 && uint64_t(size) <= limit, "input file limit");
    sf::Bytes bytes(static_cast<size_t>(size));
    in.seekg(0);
    if (!bytes.empty()) in.read(reinterpret_cast<char *>(bytes.data()), bytes.size());
    require(in.good(), "read input");
    return bytes;
}

void write(const char *path, const sf::Bytes &bytes) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!bytes.empty()) out.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    out.close();
    require(out.good(), "write output");
}

template<class Error, class Fn>
void rejects(Fn invoke, const char *expected = nullptr) {
    try {
        invoke();
    } catch (const Error &e) {
        require(!expected || std::string(e.what()) == expected, "unexpected rejection reason");
        return;
    }
    throw std::logic_error("invalid request accepted");
}

template<class T>
void vector_json(const std::vector<T> &values) {
    char sep = '[';
    for (const auto v : values) { std::cout << sep << v; sep = ','; }
    if (sep == '[') std::cout << '[';
    std::cout << ']';
}

void query_json(const sf::QueryResult &query) {
    const auto backend = query.backend == sf::QueryBackend::Scalar ? "scalar" : "upstream_simd";
    std::cout << "{\"backend\":\"" << backend << "\",\"count\":";
    vector_json(query.count);
    std::cout << ",\"sum\":"; vector_json(query.sum);
    std::cout << ",\"max\":"; vector_json(query.max);
    std::cout << '}';
}

void query_checks(sf::Codec &codec, sf::Config config, const sf::Bytes &payload, size_t size) {
    const auto automatic = codec.query(payload.data(), payload.size(), size);
    const auto scalar = codec.query(payload.data(), payload.size(), size, sf::QueryMode::Scalar);
    sf::Bytes trailing = payload;
    trailing.push_back(0);
    const auto e = config.width / 8;
    for (auto mode : {sf::QueryMode::Auto, sf::QueryMode::Scalar}) {
        rejects<std::runtime_error>([&]{ codec.query(payload.data(), payload.size()-1, size, mode); }, "malformed integer payload");
        rejects<std::runtime_error>([&]{ codec.query(trailing.data(), trailing.size(), size, mode); }, "malformed integer payload");
        rejects<std::runtime_error>([&]{ codec.query(payload.data(), payload.size(),
                                         size >= size_t(e) ? size-e : e, mode); }, "malformed integer payload");
        rejects<std::invalid_argument>([&]{ codec.query(payload.data(), payload.size(), codec.message_limit()+e, mode); }, "query size");
        if (e == 2 && size < codec.message_limit())
            rejects<std::invalid_argument>([&]{ codec.query(payload.data(), payload.size(), size+1, mode); }, "query size");
    }
    const bool lowdim = config.ndims <= (e == 1 ? 4 : 2);
    if (lowdim) {
        rejects<std::invalid_argument>([&]{ codec.query(payload.data(), payload.size(), size, sf::QueryMode::Simd); },
                                       "SIMD query requires generic packing");
    }
    std::cout << "{\"auto\":"; query_json(automatic);
    std::cout << ",\"scalar\":"; query_json(scalar);
    std::cout << ",\"query_rejections\":[\"truncated\",\"trailing\",\"wrong_raw_length\",\"above_message_limit\"";
    if (e == 2 && size < codec.message_limit()) std::cout << ",\"odd_u16_raw_length\"";
    std::cout << "],\"lowdim_forced_simd_rejected\":" << (lowdim ? "true" : "null") << "}\n";
}

void negative() {
    auto config = profile;
    for (auto dims : {0, 129}) {
        config.ndims = dims;
        rejects<std::invalid_argument>([&]{ sf::Codec bad(config); }, "Sprintz configuration");
    }
    sf::Codec codec(profile);
    const sf::Bytes oversized(max_bytes + 2);
    rejects<std::invalid_argument>([&]{ codec.encode(oversized.data(), oversized.size()); }, "input size");
    rejects<std::invalid_argument>([&]{ codec.encode(oversized.data(), 1); }, "element size");
    std::cout << "[\"zero_lanes\",\"129_lanes\",\"encode_above_default_limit\",\"encode_odd_u16_bytes\"]\n";
}
}

int main(int argc, char **argv) {
    if (!tsbench::sprintz_fire::supported_host()) {
        std::cout << "SKIP: Sprintz requires AVX2/BMI/BMI2/LZCNT/POPCNT\n";
        return 77;
    }
    try {
        if (argc == 2 && std::string(argv[1]) == "reject") { negative(); return 0; }
        require(argc == 7, "probe/decode width dims limit input output required");
        const std::string action = argv[1];
        const sf::Config config{1, std::stoi(argv[2]), std::stoi(argv[3]), 0};
        const auto limit = std::stoul(argv[4]);
        sf::Codec codec(config, limit);
        const bool encode = action == "probe" || action == "encode";
        require(encode || action == "decode" || action == "query", "unknown operation");
        const auto input = read(argv[5], encode ? limit : 32 + 4 * limit);
        if (encode) {
            const auto payload = codec.encode(input.data(), input.size());
            write(argv[6], sf::frame(config, input.data(), input.size(), payload));
            if (action == "probe") {
                query_checks(codec, config, payload, input.size());
            } else {
                std::cout << "{\"backend\":\"" << sf::backend() << "\",\"raw_bytes\":" << input.size()
                          << ",\"workspace_bytes\":" << codec.workspace_capacity() << ",\"message_limit_bytes\":"
                          << codec.message_limit() << "}\n";
            }
        } else {
            size_t size = 0;
            uint32_t crc = 0;
            const auto payload = sf::unframe(config, input.data(), input.size(), size, crc, limit);
            if (action == "query") {
                require(std::string(argv[6]) == "-", "query writes only its result transcript");
                query_checks(codec, config, payload, size);
            } else {
                const auto output = codec.decode(payload.data(), payload.size(), size);
                require(sf::crc32(output.data(), output.size()) == crc, "native raw CRC");
                write(argv[6], output);
            }
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
