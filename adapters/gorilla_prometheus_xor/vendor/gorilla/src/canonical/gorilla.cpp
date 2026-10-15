// SPDX-License-Identifier: Apache-2.0 AND BSD-2-Clause
// Structured translation of Prometheus xor.go / bstream.go; see LICENSES/NOTICE.
#include "gorilla/gorilla.hpp"
#include <algorithm>
#include <cstring>
#include <limits>
#ifdef GORILLA_HAS_OPTIMIZED
#include "../optimized/bitops.hpp"
#endif
namespace gorilla {
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
              "IEEE binary64 required");
namespace {
void check_path(Path path) {
#ifndef GORILLA_HAS_OPTIMIZED
    if (path != Path::Canonical) throw Error(Code::Unsupported, "optimized path not built");
#else
    if (path != Path::Canonical && path != Path::Optimized)
        throw Error(Code::InvalidArgument, "unknown execution path");
#endif
}
void samples_pointer(const Sample* p, std::size_t n) {
    if (n && (!p || reinterpret_cast<std::uintptr_t>(p) % alignof(Sample)))
        throw Error(Code::InvalidArgument, "null or unaligned Sample pointer");
}
unsigned leading_zeros(std::uint64_t x) {
    unsigned n = 0;
    for (auto mask = UINT64_C(1) << 63; !(x & mask); mask >>= 1) ++n;
    return n;
}
unsigned trailing_zeros(std::uint64_t x) {
    unsigned n = 0;
    while (!(x & 1)) { x >>= 1; ++n; }
    return n;
}
bool bit_range(std::int64_t x, unsigned width) {
    const auto half = INT64_C(1) << (width - 1);
    return x >= -(half - 1) && x <= half;
}
Accounting account(std::uint64_t ts, std::uint64_t value, std::size_t bytes) {
    Accounting a;
    a.timestamp_bits = ts; a.value_bits = value;
    a.serialized_bits = static_cast<std::uint64_t>(bytes) * 8;
    a.padding_bits = a.serialized_bits - 16 - ts - value;
    a.final_bits = a.serialized_bits;
    return a;
}
}
std::uint64_t double_bits(double v) noexcept {
    std::uint64_t result; std::memcpy(&result, &v, sizeof result); return result;
}
double bits_double(std::uint64_t v) noexcept {
    double result; std::memcpy(&result, &v, sizeof result); return result;
}
std::int64_t signed_bits(std::uint64_t v) noexcept {
    if (v <= static_cast<std::uint64_t>(INT64_MAX)) return static_cast<std::int64_t>(v);
    return -1 - static_cast<std::int64_t>(~v);
}
const char* path_name(Path p) noexcept {
    return p == Path::Canonical ? "canonical-scalar" : p == Path::Optimized ? "optimized-scalar" : "invalid";
}
std::size_t compress_bound(std::size_t n) {
    if (n > max_samples) throw Error(Code::Limit, "chunk sample limit exceeded");
    if (n > (std::numeric_limits<std::size_t>::max() - 7) / 157)
        throw Error(Code::Limit, "capacity overflow");
    return 2 + (n * 157 + 7) / 8;
}
Encoder::Encoder(Path path) : path_(path) { check_path(path); reset(); }
void Encoder::reset() {
    std::vector<std::uint8_t> fresh(2, 0);
    bytes_.swap(fresh); position_ = 16; count_ = 0;
    timestamp_ = static_cast<std::uint64_t>(INT64_MIN); value_ = delta_ = 0; leading_ = 255; trailing_ = 0;
    timestamp_bits_ = value_bits_ = 0; sealed_ = false; stats_ = {};
}
void Encoder::reset(const std::uint8_t* data, std::size_t size) {
    // Validate before pointer arithmetic/copy, and preserve input on failure.
    Iterator validation(data, size, path_, false, InputStorage::Borrowed);
    while (validation.next()) {}
    std::vector<std::uint8_t> fresh(data, data + size);
    reset_owned(std::move(fresh));
}
void Encoder::reset_owned(std::vector<std::uint8_t>&& raw) {
    Iterator it(raw.data(), raw.size(), path_, false, InputStorage::Borrowed);
    while (it.next()) {}
    const auto size = raw.size();
    bytes_ = std::move(raw); count_ = it.total_; position_ = size * 8;
    timestamp_ = it.timestamp_; value_ = it.value_; delta_ = it.delta_;
    leading_ = size == 2 ? 255 : it.leading_; trailing_ = it.trailing_;
    timestamp_bits_ = it.timestamp_bits_; value_bits_ = it.value_bits_;
    // Prior padding remains padding, now possibly an intermediate source gap.
    sealed_ = false; stats_ = {};
}
void Encoder::put(std::uint64_t x, unsigned width) {
#ifdef GORILLA_HAS_OPTIMIZED
    if (path_ == Path::Optimized) {
        ++stats_.optimized_fields;
        detail::write_bits(bytes_, position_, x, width); return;
    }
#endif
    stats_.canonical_bit_ops += width;
    for (unsigned k = width; k > 0; --k) {
        if (position_ / 8 == bytes_.size()) bytes_.push_back(0);
        bytes_[position_ / 8] |= static_cast<std::uint8_t>(((x >> (k - 1)) & 1) << (7 - position_ % 8));
        ++position_;
    }
}
void Encoder::put_varint(std::uint64_t x) {
    while (x >= 128) { put((x & 127) | 128, 8); x >>= 7; }
    put(x, 8);
}
void Encoder::put_value(std::uint64_t v) {
    const auto x = value_ ^ v;
    if (x == 0) { put(0, 1); return; }
    put(1, 1);
    auto l = std::min(leading_zeros(x), 31U); auto t = trailing_zeros(x);
    if (leading_ != 255 && l >= leading_ && t >= trailing_) {
        put(0, 1); put(x >> trailing_, 64 - leading_ - trailing_);
    } else {
        leading_ = l; trailing_ = t;
        put(1, 1); put(l, 5); put((64 - l - t) & 63, 6); put(x >> t, 64 - l - t);
    }
}
void Encoder::append(Sample s) {
    if (sealed_) throw Error(Code::State, "append after finalize");
    if (count_ == max_samples) throw Error(Code::Limit, "chunk capacity exceeded");
    // Reserve before changing bytes or predictor state; no allocation in bit writer.
    const auto need = std::max(bytes_.size() + 20, compress_bound(count_ + 1));
    if (need > compress_bound(max_samples)) throw Error(Code::Limit, "raw byte capacity exceeded");
    if (need > bytes_.capacity())
        bytes_.reserve(std::min(compress_bound(max_samples), std::max(need, bytes_.capacity() * 2)));
    const auto t = static_cast<std::uint64_t>(s.timestamp); std::uint64_t d = 0;
    const auto begin = position_;
    if (count_ == 0) {
        const auto zigzag = (t << 1) ^ (UINT64_C(0) - (t >> 63));
        put_varint(zigzag);
    } else {
        d = t - timestamp_;
        if (count_ == 1) put_varint(d);
        else {
            const auto dod = d - delta_; const auto signed_dod = signed_bits(dod);
            if (dod == 0) put(0, 1);
            else if (bit_range(signed_dod, 14)) { put(2, 2); put(dod, 14); }
            else if (bit_range(signed_dod, 17)) { put(6, 3); put(dod, 17); }
            else if (bit_range(signed_dod, 20)) { put(14, 4); put(dod, 20); }
            else { put(15, 4); put(dod, 64); }
        }
    }
    timestamp_bits_ += position_ - begin;
    const auto before_value = position_;
    if (count_ == 0) put(s.value_bits, 64); else put_value(s.value_bits);
    value_bits_ += position_ - before_value;
    timestamp_ = t; value_ = s.value_bits; delta_ = d;
    ++count_; bytes_[0] = static_cast<std::uint8_t>(count_ >> 8);
    bytes_[1] = static_cast<std::uint8_t>(count_ & 255);
}
void Encoder::reacquire() {
    if (!count_) { timestamp_ = static_cast<std::uint64_t>(INT64_MIN); leading_ = 255; return; }
    Iterator it(bytes_.data(), bytes_.size(), path_, false, InputStorage::Borrowed);
    while (it.next()) {}
    timestamp_ = it.timestamp_; value_ = it.value_; delta_ = it.delta_;
    leading_ = it.leading_; trailing_ = it.trailing_;
}
void Encoder::compact() { bytes_.shrink_to_fit(); }
const std::vector<std::uint8_t>& Encoder::finalize() noexcept { sealed_ = true; return bytes_; }
Accounting Encoder::accounting() const noexcept { return account(timestamp_bits_, value_bits_, bytes_.size()); }
std::array<std::uint64_t, 5> Encoder::trace() const noexcept {
    return {timestamp_, value_, delta_, leading_ | (static_cast<std::uint64_t>(trailing_) << 8),
            position_ % 8 ? 8 - position_ % 8 : 0};
}
Iterator::Iterator(const std::uint8_t* data, std::size_t size, Path path, bool strict, InputStorage storage)
    : path_(path), storage_(storage), strict_(strict) { check_path(path); reset(data, size); }
void Iterator::reset(const std::uint8_t* data, std::size_t size) {
    if (!data || size < 2) throw Error(Code::Malformed, "missing count header");
    if (size > compress_bound(max_samples)) throw Error(Code::Limit, "raw byte resource limit");
    const auto total = static_cast<std::size_t>(data[0]) * 256 + data[1];
    if (strict_ && size > compress_bound(total)) throw Error(Code::Malformed, "raw size exceeds count bound");
    if (storage_ == InputStorage::Snapshot) {
        std::vector<std::uint8_t> fresh(data, data + size);
        bytes_.swap(fresh); data_ = bytes_.data();
    } else if (storage_ == InputStorage::Borrowed) {
        data_ = data;
    } else throw Error(Code::InvalidArgument, "unknown input storage mode");
    raw_size_ = size; last_ = data_[size - 1];
    position_ = 16; total_ = total; read_ = 0;
    timestamp_ = static_cast<std::uint64_t>(INT64_MIN); value_ = delta_ = 0;
    leading_ = trailing_ = 0; timestamp_bits_ = value_bits_ = 0; failed_ = false; stats_ = {};
}
std::uint64_t Iterator::get(unsigned width) {
    if (width > 64 || width > raw_size_ * 8 - position_)
        throw Error(Code::Malformed, "truncated bit field");
#ifdef GORILLA_HAS_OPTIMIZED
    if (path_ == Path::Optimized) {
        ++stats_.optimized_fields; return detail::read_bits(data_, position_, width, raw_size_, last_);
    }
#endif
    stats_.canonical_bit_ops += width;
    std::uint64_t v = 0;
    for (unsigned k = 0; k < width; ++k) {
        const auto byte = position_ / 8 == raw_size_ - 1 ? last_ : data_[position_ / 8];
        v = (v << 1) | ((byte >> (7 - position_ % 8)) & 1);
        ++position_;
    }
    return v;
}
std::uint64_t Iterator::get_varint() {
    std::uint64_t x = 0;
    for (unsigned k = 0; k < 10; ++k) {
        const auto b = get(8);
        if (k == 9 && b > 1) throw Error(Code::Malformed, "varint overflow");
        x |= (b & 127) << (k * 7);
        if (b < 128) return x;
    }
    throw Error(Code::Malformed, "unterminated varint");
}
void Iterator::get_value() {
    if (get(1) == 0) return;
    unsigned width = 64 - leading_ - trailing_;
    if (get(1)) {
        const auto l = static_cast<unsigned>(get(5));
        auto w = static_cast<unsigned>(get(6)); if (!w) w = 64;
        if (l + w > 64) throw Error(Code::Malformed, "invalid XOR window");
        leading_ = l; trailing_ = 64 - l - w; width = w;
    }
    value_ ^= get(width) << trailing_;
}
void Iterator::check_tail() {
    if (!strict_) return;
    const auto remain = raw_size_ * 8 - position_;
    if (remain > 7) throw Error(Code::Malformed, "trailing raw bytes");
    if (remain && (last_ & ((1U << remain) - 1)))
        throw Error(Code::Malformed, "nonzero padding");
}
bool Iterator::next() {
    if (failed_) throw Error(Code::State, "iterator failed; reset required");
    try {
        if (read_ == total_) { check_tail(); return false; }
#ifdef GORILLA_HAS_OPTIMIZED
        // Source's common two-zero control shortcut, forced only on optimized path.
        if (path_ == Path::Optimized && read_ >= 2 && raw_size_ * 8 - position_ >= 2) {
            auto peek = position_;
            if (detail::read_bits(data_, peek, 2, raw_size_, last_) == 0) {
                ++stats_.repeated_pair_shortcuts;
                position_ = peek; timestamp_ += delta_; ++timestamp_bits_; ++value_bits_; ++read_;
                if (read_ == total_) check_tail();
                return true;
            }
        }
#endif
        const auto begin = position_;
        if (!read_) {
            const auto z = get_varint(); timestamp_ = (z >> 1) ^ (UINT64_C(0) - (z & 1));
        } else if (read_ == 1) {
            delta_ = get_varint(); timestamp_ += delta_;
        } else {
            unsigned prefix = 0;
            for (unsigned k = 0; k < 4; ++k) { prefix <<= 1; if (!get(1)) break; prefix |= 1; }
            unsigned width = prefix == 2 ? 14 : prefix == 6 ? 17 : prefix == 14 ? 20 : prefix == 15 ? 64 : 0;
            std::uint64_t dod = 0;
            if (width) {
                dod = get(width);
                if (width < 64 && dod > (UINT64_C(1) << (width - 1))) dod -= UINT64_C(1) << width;
            }
            delta_ += dod; timestamp_ += delta_;
        }
        timestamp_bits_ += position_ - begin;
        const auto before_value = position_;
        if (!read_) value_ = get(64); else get_value();
        value_bits_ += position_ - before_value; ++read_;
        if (read_ == total_) check_tail();
        return true;
    } catch (...) { failed_ = true; throw; }
}
bool Iterator::seek(std::int64_t t) {
    if (failed_) throw Error(Code::State, "iterator failed; reset required");
    while (t > signed_bits(timestamp_) || read_ == 0) if (!next()) return false;
    return true;
}
Sample Iterator::at() const {
    if (!read_ || failed_) throw Error(Code::State, "no current sample");
    return {signed_bits(timestamp_), value_};
}
Accounting Iterator::accounting() const {
    if (failed_ || read_ != total_) throw Error(Code::State, "accounting requires complete successful iteration");
    return account(timestamp_bits_, value_bits_, raw_size_);
}
std::array<std::uint64_t, 5> Iterator::trace() const noexcept {
    return {timestamp_, value_, delta_, leading_ | (static_cast<std::uint64_t>(trailing_) << 8),
            position_ % 8 ? 8 - position_ % 8 : 0};
}
std::vector<std::uint8_t> encode(const Sample* input, std::size_t n, Path path) {
    compress_bound(n); samples_pointer(input, n); Encoder e(path);
    for (std::size_t k = 0; k < n; ++k) e.append(input[k]);
    return e.finalize();
}
std::vector<Sample> decode(const std::uint8_t* input, std::size_t size, Path path, bool strict) {
    Iterator it(input, size, path, strict); std::vector<Sample> out; out.reserve(it.count());
    while (it.next()) out.push_back(it.at());
    return out;
}
std::size_t compress(const Sample* input, std::size_t n, std::uint8_t* output, std::size_t cap, Path path) {
    const auto bound = compress_bound(n);
    if (cap < bound) throw Error(Code::Capacity, "output smaller than compress_bound");
    if (!output) throw Error(Code::InvalidArgument, "null byte output");
    auto encoded = encode(input, n, path); std::memcpy(output, encoded.data(), encoded.size());
    return encoded.size();
}
std::size_t decompress(const std::uint8_t* input, std::size_t size, Sample* output, std::size_t cap, Path path, bool strict) {
    Iterator it(input, size, path, strict);
    if (cap < it.count()) throw Error(Code::Capacity, "sample output capacity");
    samples_pointer(output, it.count()); auto result = decode(input, size, path, strict);
    if (!result.empty()) std::memcpy(output, result.data(), result.size() * sizeof(Sample));
    return result.size();
}
} // namespace gorilla
