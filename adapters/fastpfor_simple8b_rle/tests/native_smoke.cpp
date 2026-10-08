// Functional evidence for the actual shared library; not the full native qualification.
#include "wire_oracle.hpp"
#include "tscb_adapter_v1.h"
#include <cstdlib>
#include <string>

extern "C" tscb_status_v1 tscb_get_telemetry_json(tscb_codec_handle_v1*, const char**, uint64_t*);
namespace {
tscb_buffer_v1 descriptor(void *data, uint64_t bytes, uint64_t used, bool integer) {
    tscb_buffer_v1 b{};
    b.data = data; b.capacity_bytes = bytes; b.used_bytes = used;
    b.dtype = integer ? TSCB_DTYPE_U32_LE_V1 : TSCB_DTYPE_BYTES_V1;
    b.rank = 1; b.shape[0] = integer ? bytes / 4 : bytes;
    b.strides_bytes[0] = integer ? 4 : 1; b.alignment_bytes = 1;
    return b;
}
void ok(tscb_status_v1 code) { check(code == TSCB_STATUS_OK_V1, "native status not OK"); }
tscb_codec_handle_v1* create(bool marked) {
    const std::string json = std::string("{\"codec\":\"SIMPLE8B_RLE\",\"isa\":\"SCALAR\",\"mark_length\":")
                             + (marked ? "true}" : "false}");
    tscb_codec_handle_v1 *h = nullptr;
    ok(tscb_create(json.data(), json.size(), &h));
    tscb_native_timing_v1 unavailable{sizeof(unavailable), 1, 991, 992};
    check(tscb_get_native_timing(h, &unavailable) == TSCB_STATUS_UNSUPPORTED_V1 &&
          unavailable.native_encode_wall_ns == 991 && unavailable.native_decode_wall_ns == 992,
          "native timing was not initially disabled");
    ok(tscb_set_native_timing(h, 1));
    return h;
}
uint64_t little(const unsigned char *p, unsigned n) {
    uint64_t value = 0;
    for (unsigned i = 0; i < n; ++i) value |= uint64_t(p[i]) << (8 * i);
    return value;
}
uint64_t json_integer(const char *json, const char *key) {
    const std::string needle = std::string("\"") + key + "\":";
    const char *p = std::strstr(json, needle.c_str());
    check(p != nullptr, "missing native ledger field");
    return std::strtoull(p + needle.size(), nullptr, 10);
}
tscb_native_timing_v1 timing(tscb_codec_handle_v1 *h) {
    tscb_native_timing_v1 value{sizeof(value), 1, 0, 0};
    ok(tscb_get_native_timing(h, &value));
    return value;
}
void one(const std::vector<uint32_t>& values, bool marked, unsigned offset) {
    const size_t n = values.size();
    const auto words = oracle(values);
    const size_t count = words.size() * 2 + (marked ? 1 : 0);
    const size_t exact = 40 + count * 4;
    auto *encoder = create(marked), *decoder = create(!marked);
    std::vector<unsigned char> raw(n * 4 + offset + 16, 0x5a);
    if (n) std::memcpy(raw.data() + offset, values.data(), n * 4);
    const auto immutable = raw;
    auto input = descriptor(raw.data() + offset, n * 4, n * 4, true);
    uint64_t bound = 0;
    ok(tscb_compress_bound(encoder, &input, &bound));
    check(bound == 40 + n * 8 + (marked ? 4 : 0) && exact <= bound, "native bound differs");
    std::vector<unsigned char> bytes(exact + offset + 16, 0xa5);
    auto packed = descriptor(bytes.data() + offset, exact - 1, 0, false);
    const auto descriptor_before = packed;
    check(tscb_compress(encoder, &input, &packed) == TSCB_STATUS_DST_TOO_SMALL_V1,
          "short encode capacity accepted");
    check(std::memcmp(&packed, &descriptor_before, sizeof(packed)) == 0 &&
          std::all_of(bytes.begin(), bytes.end(), [](unsigned char v){return v == 0xa5;}),
          "short encode published partial output");
    packed = descriptor(bytes.data() + offset, exact, 0, false);
    ok(tscb_compress(encoder, &input, &packed)); // Retry without resetting a failed operation.
    check(raw == immutable && packed.used_bytes == exact, "native input/count differs");
    auto *wire = bytes.data() + offset;
    check(std::memcmp(wire, "TSCB8BR1", 8) == 0 && little(wire + 8, 4) == n &&
          little(wire + 12, 4) == 0 && little(wire + 16, 4) == marked &&
          little(wire + 20, 4) == count, "native frame differs");
    if (marked) check(little(wire + 32, 4) == n, "native source marker differs");
    for (size_t i = 0; i < words.size(); ++i)
        check(little(wire + 32 + (marked ? 4 : 0) + i * 8, 8) == words[i],
              "native library bypassed original source wire");
    for (size_t i = 0; i < offset; ++i) check(bytes[i] == 0xa5, "encode prefix changed");
    for (size_t i = offset + exact; i < bytes.size(); ++i)
        check(bytes[i] == 0xa5, "encode suffix changed");
    auto final = descriptor(nullptr, 0, 0, false);
    ok(tscb_finalize(encoder, &final));
    check(tscb_finalize(encoder, &final) == TSCB_STATUS_CODEC_ERROR_V1, "repeat finalize accepted");
    const char *json; uint64_t length;
    ok(tscb_get_accounting_json(encoder, &json, &length));
    uint64_t total = 0;
    for (const char *key : {"container_bits", "metadata_bits", "checksum_bits", "value_bits",
                            "padding_bits"}) total += json_integer(json, key);
    check(total == exact * 8 && json_integer(json, "final_bits") == total,
          "native physical ledger does not close");
    uint64_t value_bits = 0, padding_bits = 0, counts_metadata = 0, logical = 0;
    for (uint64_t word : words) {
        const unsigned selector = unsigned(word >> 60);
        if (selector == 15) {
            value_bits += 32; counts_metadata += 28;
            logical += (word >> 32) & 0x0fffffffU;
        } else {
            const unsigned used = std::min<uint64_t>(capacities[selector], n - logical);
            value_bits += used * std::min(widths[selector], 32U);
            padding_bits += 60 - used * std::min(widths[selector], 32U);
            logical += used;
        }
    }
    check(json_integer(json, "value_bits") == value_bits &&
          json_integer(json, "padding_bits") == padding_bits &&
          json_integer(json, "metadata_bits") == 192 + (marked ? 32 : 0) +
          words.size() * 4 + counts_metadata, "native RLE/selector accounting differs");
    const auto first = timing(encoder), second = timing(encoder);
    check(first.native_encode_wall_ns == second.native_encode_wall_ns &&
          first.native_decode_wall_ns == 0, "native timer query/direction differs");
    auto compressed = descriptor(wire, exact, exact, false);
    const auto bytes_before = bytes;
    std::vector<unsigned char> recovered(n * 4 + offset + 16, 0xcc);
    auto decoded = descriptor(recovered.data() + offset, n * 4, 0, true);
    ok(tscb_decompress(decoder, &compressed, &decoded));
    check(decoded.used_bytes == n * 4 && (!n || std::memcmp(decoded.data, values.data(), n * 4) == 0)
          && bytes == bytes_before, "native fresh opposite-config decoder differs");
    for (size_t i = 0; i < offset; ++i) check(recovered[i] == 0xcc, "decode prefix changed");
    for (size_t i = offset + n * 4; i < recovered.size(); ++i)
        check(recovered[i] == 0xcc, "decode suffix changed");
    const auto decoded_first = timing(decoder);
    decoded.used_bytes = 0; ok(tscb_decompress(decoder, &compressed, &decoded));
    check(timing(decoder).native_decode_wall_ns >= decoded_first.native_decode_wall_ns,
          "native decoder time did not accumulate");
    ok(tscb_get_telemetry_json(decoder, &json, &length));
    check(json_integer(json, "native_raw_bytes") == n * 4 &&
          json_integer(json, "native_payload_bytes") == count * 4, "native telemetry differs");
    ok(tscb_set_native_timing(encoder, 0)); ok(tscb_reset(encoder, 0));
    std::vector<unsigned char> untimed(exact);
    auto sink = descriptor(untimed.data(), exact, 0, false);
    ok(tscb_compress(encoder, &input, &sink));
    check(std::equal(untimed.begin(), untimed.end(), wire), "timer toggle changed native wire");
    tscb_native_timing_v1 unavailable{sizeof(unavailable), 1, 991, 992};
    check(tscb_get_native_timing(encoder, &unavailable) == TSCB_STATUS_UNSUPPORTED_V1 &&
          unavailable.native_encode_wall_ns == 991, "disabled native timer published fake zero");
    ok(tscb_destroy(encoder)); ok(tscb_destroy(decoder));
}
} // namespace

int main() {
    try {
        uint64_t native_cases = 0;
        for (unsigned width = 0; width <= 32; ++width)
            for (size_t n : {0,1,2,3,7,8,9,29,30,60,61,127,128,129,255,256,257})
                for (unsigned kind = 0; kind < 6; ++kind)
                    for (bool marked : {false,true}) for (unsigned offset = 0; offset < 4; ++offset) {
                        one(pattern(n, width, kind), marked, offset);
                        ++native_cases;
                    }
        std::printf("{\"status\":\"PASS\",\"native_functional_cases\":%llu,"
                    "\"full_native_qualification\":false}\n",
                    static_cast<unsigned long long>(native_cases));
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "NATIVE_SMOKE_FAIL: %s\n", error.what());
        return 2;
    }
}
