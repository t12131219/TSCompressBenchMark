// Reuse exactly the legacy page-group caller (including lifecycle and clocks).
// The PGF1 object is a harness envelope; each contained PM3PAGE1 frame is unchanged.
#define TSBENCH_PCODEC_GROUPED 1
#include "pages_control.cpp"
#include <algorithm>
#include <fstream>

namespace {
constexpr char raw_magic[8] = {'P','G','F','1','R','A','W','\0'};
constexpr char frame_magic[8] = {'P','G','F','1','P','A','G','E'};
constexpr size_t max_columns = 4096, max_rows = 10000000;

size_t number(const char *text, size_t max) {
    const std::string_view s(text);
    size_t n = 0;
    const auto [end, err] = std::from_chars(s.data(), s.data() + s.size(), n);
    check(err == std::errc{} && end == s.data() + s.size() && n && n <= max, "invalid declared corpus geometry");
    return n;
}
void write(std::ostream &out, const void *value, size_t n) {
    check(bool(out.write(static_cast<const char *>(value), static_cast<std::streamsize>(n))), "grouped page write failed");
}
void read(std::istream &in, void *value, size_t n) {
    check(bool(in.read(static_cast<char *>(value), static_cast<std::streamsize>(n))), "short grouped page record");
}
void u32(std::ostream &out, size_t value) {
    check(value <= UINT32_MAX, "grouped page integer overflow");
    const uint8_t a[] = {uint8_t(value), uint8_t(value >> 8), uint8_t(value >> 16), uint8_t(value >> 24)};
    write(out, a, sizeof(a));
}
size_t u32(std::istream &in) {
    uint8_t a[4];
    read(in, a, sizeof(a));
    return size_t(a[0]) | size_t(a[1]) << 8 | size_t(a[2]) << 16 | size_t(a[3]) << 24;
}

template<class Api>
void grouped(bool encode, size_t cols, size_t rows, const char *source, const char *dest) {
    std::ifstream in(source, std::ios::binary);
    check(bool(in), "grouped page input open failed");
    char received[8];
    read(in, received, sizeof(received));
    check(std::memcmp(received, encode ? raw_magic : frame_magic, sizeof(received)) == 0 &&
          u32(in) == cols && u32(in) == rows, "grouped page header differs");
    std::ofstream out(dest, std::ios::binary | std::ios::trunc);
    check(bool(out), "grouped page output open failed");
    write(out, encode ? frame_magic : raw_magic, sizeof(received));
    u32(out, cols);
    u32(out, rows);
    for (size_t c = 0; c < cols; ++c) {
        for (size_t start = 0; start < rows; start += corpus_rows) {
            const size_t count = std::min(corpus_rows, rows - start);
            const size_t n = u32(in);
            check(encode ? n == count * width : n >= 16 && n <= corpus_max_frame, "grouped page record outside bounds");
            Bytes raw(n);
            read(in, raw.data(), n);
            auto sink = [&](const Bytes &result) {
                check(encode ? result.size() >= 16 && result.size() <= corpus_max_frame : result.size() == count * width,
                      "grouped page output extent differs");
                u32(out, result.size());
                write(out, result.data(), result.size());
            };
            if (encode) corpus_encode_bytes<Api>(raw, sink);
            else corpus_decode_bytes<Api>(raw, sink);
        }
    }
    check(in.peek() == std::char_traits<char>::eof() && in.eof() && !in.bad(), "trailing grouped page input");
    out.close();
    check(out.good(), "grouped page output close failed");
}
}

int main(int argc, char **argv) {
    try {
        if (argc != 7 || !pc_source_backend_available()) return 2;
        const std::string_view op(argv[1]), lane(argv[2]);
        if ((op != "encode" && op != "decode") || (lane != "source" && lane != "native")) return 2;
        const auto cols = number(argv[3], max_columns), rows = number(argv[4], max_rows);
        if (lane == "source") grouped<Source>(op == "encode", cols, rows, argv[5], argv[6]);
        else grouped<Native>(op == "encode", cols, rows, argv[5], argv[6]);
        return std::fflush(stdout) == 0 && !std::ferror(stdout) ? 0 : 3;
    } catch (const std::exception &exc) {
        std::fprintf(stderr, "pcodec grouped pages: %s\n", exc.what());
        return 1;
    }
}
