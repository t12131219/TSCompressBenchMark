#include "alp_port.h"
#include "alp.hpp"
#include <algorithm>
#include <array>
#include <cfenv>
#include <cstring>
#include <limits>
#include <new>
#include <stdexcept>
#include <vector>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif

namespace {
constexpr size_t B = 1024, RG = 102400, HEADER = 32;
struct Failure { int status; };
void need(bool condition, int status = ALP_MALFORMED) {
    if (!condition) throw Failure{status};
}
bool params(uint8_t d, uint8_t m) { return (d == 4 || d == 8) && m <= 1; }
size_t bound_for(uint64_t n) { return HEADER + static_cast<size_t>((n + B - 1) / B) * 32800; }
bool overlap(const void* a, size_t na, const void* b, size_t nb) {
    if (!na || !nb) return false;
    const auto x = reinterpret_cast<uintptr_t>(a), y = reinterpret_cast<uintptr_t>(b);
    if (na > UINTPTR_MAX - x || nb > UINTPTR_MAX - y) return true;
    return x < y + nb && y < x + na;
}
bool fp_ok() {
    if (std::fegetround() != FE_TONEAREST) return false;
#if defined(__SSE__)
    const auto csr = _mm_getcsr();
    if (csr & ((1u << 15) | (1u << 6) | (3u << 13))) return false;
    if ((csr & 0x1f80u) != 0x1f80u) return false;
    uint16_t cw; asm volatile("fnstcw %0" : "=m"(cw));
    if ((cw & 0x3fu) != 0x3fu) return false;
#elif defined(__aarch64__)
    uint64_t fpcr; asm volatile("mrs %0, fpcr" : "=r"(fpcr));
    if (fpcr & ((UINT64_C(1) << 24) | (UINT64_C(1) << 19) | UINT64_C(0x9f00))) return false;
#endif
    return true;
}
uint32_t crc_step(uint32_t crc, const uint8_t* p, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        crc ^= p[i];
        for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return crc;
}
uint32_t frame_crc(const uint8_t* p, size_t n) {
    return ~crc_step(crc_step(~0u, p, 28), p + HEADER, n - HEADER);
}
struct Writer {
    std::vector<uint8_t> bytes;
    void u(uint64_t x, size_t n) {
        for (size_t i = 0; i < n; ++i) { bytes.push_back(static_cast<uint8_t>(x)); x >>= 8; }
    }
    void zeros(size_t n) { bytes.insert(bytes.end(), n, 0); }
    template<class T> void words(const T* p, size_t n) {
        using U = std::make_unsigned_t<T>;
        for (size_t i = 0; i < n; ++i) { U x; std::memcpy(&x, p + i, sizeof(T)); u(x, sizeof(T)); }
    }
    void set(size_t offset, uint64_t x, size_t n) {
        for (size_t i = 0; i < n; ++i) { bytes.at(offset + i) = static_cast<uint8_t>(x); x >>= 8; }
    }
};
struct Reader {
    const uint8_t* p; size_t n, off = 0;
    uint64_t u(size_t k) {
        need(k <= n - off); uint64_t x = 0;
        for (size_t i = 0; i < k; ++i) x |= uint64_t(p[off++]) << (i * 8);
        return x;
    }
    void zeros(size_t k) { for (size_t i = 0; i < k; ++i) need(u(1) == 0); }
    template<class T> void words(T* out, size_t k) {
        using U = std::make_unsigned_t<T>;
        need(k <= (n - off) / sizeof(T));
        for (size_t i = 0; i < k; ++i) { const U x = static_cast<U>(u(sizeof(T))); std::memcpy(out + i, &x, sizeof(T)); }
    }
};

template<class T> Writer encode(const uint8_t* data, size_t count, uint8_t method) {
    using S = typename alp::inner_t<T>::st; using U = typename alp::inner_t<T>::ut;
    Writer w; w.bytes.reserve(std::min(bound_for(count), size_t(1 << 20)));
    for (const char c : std::array<char, 8>{'A','L','P','R','W','0','0','1'}) w.u(c, 1);
    w.u(sizeof(T), 1); w.u(method, 1); w.zeros(2); w.u(count, 8); w.zeros(12);
    for (size_t offset = 0; offset < count; offset += RG) {
        const size_t logical = std::min(RG, count - offset), padded = (logical + B - 1) / B * B;
        std::vector<T> input(padded, T(0)); std::memcpy(input.data(), data + offset * sizeof(T), logical * sizeof(T));
        alignas(64) std::array<T, B> sample{}, exceptions{};
        alignas(64) std::array<S, B> digits{}, packed{};
        alignas(64) std::array<U, B> right{}, packed_right{};
        alignas(64) std::array<uint16_t, B> left{}, packed_left{}, positions{}, rd_exc{};
        uint16_t ec = 0; alp::state<T> state;
        if (method == ALP_RD) alp::rd_encoder<T>::init(input.data(), 0, padded, sample.data(), state);
        else {
            alp::encoder<T>::init(input.data(), 0, padded, sample.data(), state);
            if (state.scheme == alp::Scheme::ALP_RD)
                alp::rd_encoder<T>::init(input.data(), 0, padded, sample.data(), state);
        }
        const bool rd = state.scheme == alp::Scheme::ALP_RD;
        w.u(rd ? 1 : 2, 1); w.u(rd ? state.right_bit_width : 0, 1);
        w.u(rd ? state.left_bit_width : 0, 1); w.u(rd ? state.actual_dictionary_size : 0, 1);
        w.u(logical, 4);
        for (auto x : state.left_parts_dict) w.u(rd ? x : 0, 2);
        w.zeros(8);
        for (size_t v = 0; v < padded; v += B) {
            uint8_t bw = 0; S base = 0;
            if (rd) {
                alp::rd_encoder<T>::encode(input.data() + v, rd_exc.data(), positions.data(), &ec, right.data(), left.data(), state);
                ffor::ffor(right.data(), packed_right.data(), state.right_bit_width, &state.right_for_base);
                ffor::ffor(left.data(), packed_left.data(), state.left_bit_width, &state.left_for_base);
            } else {
                alp::encoder<T>::encode(input.data() + v, exceptions.data(), positions.data(), &ec, digits.data(), state);
                alp::encoder<T>::analyze_ffor(digits.data(), bw, &base);
                ffor::ffor(digits.data(), packed.data(), bw, &base);
            }
            w.u(std::min(B, logical - v), 2); w.u(ec, 2);
            w.u(bw, 1); w.u(rd ? 0 : state.fac, 1); w.u(rd ? 0 : state.exp, 1); w.zeros(1);
            U base_bits; std::memcpy(&base_bits, &base, sizeof(S)); w.u(base_bits, 8);
            if (rd) {
                w.words(packed_right.data(), size_t(state.right_bit_width) * 128 / sizeof(U));
                w.words(packed_left.data(), size_t(state.left_bit_width) * 128 / sizeof(uint16_t));
            } else w.words(packed.data(), size_t(bw) * 128 / sizeof(S));
            for (size_t j = 0; j < ec; ++j) {
                w.u(positions[j], 2);
                if (rd) w.u(rd_exc[j], 2);
                else { U bits; std::memcpy(&bits, &exceptions[j], sizeof(T)); w.u(bits, sizeof(T)); }
            }
        }
    }
    w.set(20, w.bytes.size() - HEADER, 8);
    w.set(28, frame_crc(w.bytes.data(), w.bytes.size()), 4);
    need(w.bytes.size() <= bound_for(count), ALP_INTERNAL);
    return w;
}

template<class T> std::vector<T> decode(Reader& r, size_t count, uint8_t method) {
    using S = typename alp::inner_t<T>::st; using U = typename alp::inner_t<T>::ut;
    std::vector<T> result(count);
    alignas(64) std::array<S, B> packed{};
    alignas(64) std::array<U, B> pr{}, right{};
    alignas(64) std::array<uint16_t, B> pl{}, left{}, pos{}, exc{};
    alignas(64) std::array<T, B> values{}, exceptions{};
    for (size_t offset = 0; offset < count; offset += RG) {
        alp::state<T> st; const auto scheme = r.u(1);
        need(scheme == 1 || scheme == 2); const bool rd = scheme == 1;
        need(method != ALP_RD || rd);
        st.right_bit_width = r.u(1); st.left_bit_width = r.u(1); st.actual_dictionary_size = r.u(1);
        const size_t logical = r.u(4); need(logical == std::min(RG, count - offset));
        for (auto& x : st.left_parts_dict) x = r.u(2);
        r.zeros(8);
        if (rd) {
            need(st.right_bit_width >= sizeof(U) * 8 - 16 && st.right_bit_width < sizeof(U) * 8);
            need(st.actual_dictionary_size >= 1 && st.actual_dictionary_size <= 8);
            need(st.left_bit_width >= 1 && st.left_bit_width <= 3 && st.actual_dictionary_size <= (1u << st.left_bit_width));
            const auto hi_limit = UINT32_C(1) << (sizeof(U) * 8 - st.right_bit_width);
            for (size_t j = 0; j < 8; ++j) {
                need(st.left_parts_dict[j] < hi_limit);
                if (j >= st.actual_dictionary_size) need(st.left_parts_dict[j] == 0);
                else for (size_t k = 0; k < j; ++k) need(st.left_parts_dict[k] != st.left_parts_dict[j]);
            }
        } else {
            need(!st.right_bit_width && !st.left_bit_width && !st.actual_dictionary_size);
            for (auto x : st.left_parts_dict) need(x == 0);
        }
        for (size_t v = 0; v < logical; v += B) {
            const size_t vn = r.u(2); need(vn == std::min(B, logical - v));
            uint16_t ec = r.u(2); need(ec <= B);
            const uint8_t bw = r.u(1), fac = r.u(1), exp = r.u(1); r.zeros(1);
            const uint64_t base64 = r.u(8); const U base_bits = static_cast<U>(base64);
            S base; std::memcpy(&base, &base_bits, sizeof(S));
            std::array<bool, B> exceptional{};
            if (rd) {
                need(!bw && !fac && !exp && !base64);
                r.words(pr.data(), size_t(st.right_bit_width) * 128 / sizeof(U));
                r.words(pl.data(), size_t(st.left_bit_width) * 128 / sizeof(uint16_t));
                unffor::unffor(pr.data(), right.data(), st.right_bit_width, &st.right_for_base);
                unffor::unffor(pl.data(), left.data(), st.left_bit_width, &st.left_for_base);
            } else {
                need(bw <= sizeof(S) * 8 && fac < std::size(alp::Constants<T>::FACT_ARR) && exp <= alp::Constants<T>::MAX_EXPONENT && fac <= exp);
                if constexpr (sizeof(U) == 4) need(base64 <= UINT32_MAX);
                r.words(packed.data(), size_t(bw) * 128 / sizeof(S));
                generated::falp::fallback::scalar::falp(packed.data(), values.data(), bw, &base, fac, exp);
            }
            for (size_t j = 0; j < ec; ++j) {
                pos[j] = r.u(2); need(pos[j] < B && (j == 0 || pos[j] > pos[j - 1])); exceptional[pos[j]] = true;
                if (rd) {
                    exc[j] = r.u(2); need(exc[j] < (UINT32_C(1) << (sizeof(U) * 8 - st.right_bit_width)));
                } else { const U x = static_cast<U>(r.u(sizeof(U))); std::memcpy(&exceptions[j], &x, sizeof(T)); }
            }
            if (rd) {
                for (size_t j = 0; j < B; ++j) {
                    need(exceptional[j] || left[j] < st.actual_dictionary_size);
                    // Exceptions may carry a truncated dictionary index. Source
                    // packed indices are <=7, so its fixed 8-entry array is safe.
                    need(left[j] < 8);
                }
                alp::rd_encoder<T>::decode(values.data(), right.data(), left.data(), exc.data(), pos.data(), &ec, st);
            } else alp::decoder<T>::patch_exceptions(values.data(), exceptions.data(), pos.data(), &ec);
            std::memcpy(result.data() + offset + v, values.data(), vn * sizeof(T));
        }
    }
    need(r.off == r.n);
    return result;
}
template<class F> int guarded(F&& f) noexcept {
    try { f(); return ALP_OK; }
    catch (Failure e) { return e.status; }
    catch (const std::bad_alloc&) { return ALP_OUT_OF_MEMORY; }
    catch (...) { return ALP_INTERNAL; }
}
}
extern "C" {
const char* alp_port_profile() {
#ifdef __AVX2__
    return "alp-cwida/safe-v1/cxx17/avx2-compiled";
#else
    return "alp-cwida/safe-v1/cxx17/portable";
#endif
}
const char* alp_port_status_string(int status) {
    static const char* names[] = {"ok", "invalid_argument", "capacity", "malformed", "resource_limit", "fp_environment", "out_of_memory", "internal"};
    return status >= 0 && status <= 7 ? names[status] : "unknown";
}
int alp_port_bound(uint64_t n, uint8_t d, uint8_t m, size_t* bound) {
    if (!bound) return ALP_INVALID_ARGUMENT; *bound = 0;
    if (!params(d, m)) return ALP_INVALID_ARGUMENT;
    if (n > ALP_PORT_MAX_VALUES) return ALP_RESOURCE_LIMIT;
    *bound = bound_for(n); return ALP_OK;
}
int alp_port_encode(const void* input, uint64_t n, uint8_t d, uint8_t m, void* output, size_t cap, size_t* used) {
    if (!used) return ALP_INVALID_ARGUMENT; *used = 0;
    if (!params(d, m) || (!input && n) || !output) return ALP_INVALID_ARGUMENT;
    if (n > ALP_PORT_MAX_VALUES) return ALP_RESOURCE_LIMIT;
    if (overlap(input, size_t(n) * d, output, cap)) return ALP_INVALID_ARGUMENT;
    if (!fp_ok()) return ALP_FP_ENV;
    return guarded([&] {
        Writer w = d == 4 ? encode<float>(static_cast<const uint8_t*>(input), n, m) : encode<double>(static_cast<const uint8_t*>(input), n, m);
        need(cap >= w.bytes.size(), ALP_CAPACITY);
        std::memcpy(output, w.bytes.data(), w.bytes.size()); *used = w.bytes.size();
    });
}
int alp_port_decode(const void* input, size_t nb, void* output, size_t cap, size_t* used, size_t* consumed, uint64_t* count, uint8_t* dtype, uint8_t* method) {
    if (used) *used = 0; if (consumed) *consumed = 0; if (count) *count = 0;
    if (dtype) *dtype = 0; if (method) *method = 0;
    if (!used || !consumed || !count || !dtype || !method || !input || (!output && cap)) return ALP_INVALID_ARGUMENT;
    if (overlap(input, nb, output, cap)) return ALP_INVALID_ARGUMENT;
    if (!fp_ok()) return ALP_FP_ENV;
    return guarded([&] {
        need(nb >= HEADER);
        const auto* p = static_cast<const uint8_t*>(input); need(std::memcmp(p, "ALPRW001", 8) == 0);
        Reader r{p, nb, 8}; const uint8_t d = r.u(1), m = r.u(1); need(params(d, m)); r.zeros(2);
        const uint64_t n = r.u(8), payload = r.u(8); const auto crc = r.u(4);
        need(n <= ALP_PORT_MAX_VALUES, ALP_RESOURCE_LIMIT);
        need(payload == nb - HEADER && nb <= bound_for(n));
        need(crc == frame_crc(p, nb));
        need(cap >= n * d && (output || n == 0), ALP_CAPACITY);
        if (d == 4) { auto x = decode<float>(r, n, m); if (n) std::memcpy(output, x.data(), n * d); }
        else { auto x = decode<double>(r, n, m); if (n) std::memcpy(output, x.data(), n * d); }
        *used = size_t(n) * d; *consumed = nb; *count = n; *dtype = d; *method = m;
    });
}
}
