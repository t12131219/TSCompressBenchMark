// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0

#include "prometheus_xor2_chunk_c.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

std::vector<pxor2_sample_v1> make_samples(std::size_t count) {
    std::vector<pxor2_sample_v1> result(count);
    for (std::size_t index = 0; index < count; ++index) {
        const std::int64_t timestamp = static_cast<std::int64_t>(1000 + index * 10);
        const std::int64_t st = index < 3 ? 0 : timestamp - static_cast<std::int64_t>(index % 17);
        const std::uint64_t value = index % 31 == 0 ? UINT64_C(0x7ff0000000000002) :
            UINT64_C(0x3ff0000000000000) ^ static_cast<std::uint64_t>(index);
        result[index] = {st, timestamp, value};
    }
    return result;
}

void roundtrip(std::size_t count) {
    pxor2_codec_v1* encoder = nullptr;
    pxor2_codec_v1* decoder = nullptr;
    require(pxor2_create_v1(&encoder) == PXOR2_STATUS_OK_V1, "encoder create failed");
    require(pxor2_create_v1(&decoder) == PXOR2_STATUS_OK_V1, "decoder create failed");
    const std::vector<pxor2_sample_v1> samples = make_samples(count);
    const pxor2_sample_v1* input = samples.empty() ? nullptr : samples.data();

    std::uint64_t bound = 0;
    require(pxor2_compress_bound_v1(encoder, input, count, &bound) == PXOR2_STATUS_OK_V1,
            "exact bound failed");
    require(bound >= 3, "bound omitted header");
    std::vector<std::uint8_t> encoded(static_cast<std::size_t>(bound) + 1, UINT8_C(0xa5));
    std::uint64_t written = 99;
    require(pxor2_compress_v1(encoder, input, count, encoded.data(), bound - 1, &written) ==
                PXOR2_STATUS_DST_TOO_SMALL_V1,
            "short destination accepted");
    require(written == 0 && encoded[bound] == UINT8_C(0xa5), "failed write changed output guard");
    require(pxor2_reset_v1(encoder) == PXOR2_STATUS_OK_V1, "reset failed");
    require(pxor2_compress_v1(encoder, input, count, encoded.data(), bound, &written) ==
                PXOR2_STATUS_OK_V1,
            "compress failed");
    require(written == bound && encoded[bound] == UINT8_C(0xa5), "exact bound or guard differs");
    std::uint64_t finalized = 99;
    require(pxor2_finalize_v1(encoder, nullptr, 0, &finalized) == PXOR2_STATUS_OK_V1 &&
                finalized == 0,
            "finalize failed");

    pxor2_accounting_v1 accounting{};
    accounting.struct_size = sizeof(accounting);
    require(pxor2_get_accounting_v1(encoder, &accounting) == PXOR2_STATUS_OK_V1,
            "accounting failed");
    require(accounting.sample_count == count &&
                accounting.canonical_raw_bits == count * 192 &&
                accounting.container_and_st_header_bits +
                    accounting.joint_timestamp_value_st_and_padding_bits ==
                    accounting.serialized_bits &&
                accounting.external_side_information_bits == 0 &&
                accounting.final_bits == written * 8,
            "accounting does not close");

    std::vector<pxor2_sample_v1> decoded(count);
    std::uint64_t decoded_count = 0;
    require(pxor2_decompress_v1(decoder, encoded.data(), written,
                                decoded.empty() ? nullptr : decoded.data(), count,
                                &decoded_count) == PXOR2_STATUS_OK_V1,
            "decompress failed");
    require(decoded_count == count &&
                (count == 0 || std::memcmp(samples.data(), decoded.data(), count * sizeof(samples[0])) == 0),
            "decoded triples differ");
    if (written > 3) {
        decoded_count = 99;
        require(pxor2_decompress_v1(decoder, encoded.data(), written - 1,
                                    decoded.empty() ? nullptr : decoded.data(), count,
                                    &decoded_count) == PXOR2_STATUS_CORRUPT_STREAM_V1 &&
                    decoded_count == 0,
                "truncated stream accepted");
    }
    require(pxor2_destroy_v1(encoder) == PXOR2_STATUS_OK_V1, "encoder destroy failed");
    require(pxor2_destroy_v1(decoder) == PXOR2_STATUS_OK_V1, "decoder destroy failed");
}

}  // namespace

int main() {
    require(pxor2_get_api_version_v1() == PXOR2_STANDALONE_API_VERSION_V1,
            "API version differs");
    const char* manifest = nullptr;
    std::uint64_t manifest_size = 0;
    require(pxor2_get_manifest_json_v1(&manifest, &manifest_size) == PXOR2_STATUS_OK_V1,
            "manifest failed");
    const std::string text(manifest, manifest_size);
    require(text.find("prometheus-xor2-chunk") != std::string::npos &&
                text.find("tscb_adapter") == std::string::npos,
            "manifest identity differs");
    for (std::size_t count : {0U, 1U, 2U, 127U, 128U, 129U, 1024U}) {
        roundtrip(count);
    }
    require(pxor2_destroy_v1(nullptr) == PXOR2_STATUS_OK_V1, "destroy null failed");
    std::cout << "prometheus-xor2-chunk standalone preflight passed\n";
    return 0;
}
