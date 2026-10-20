#pragma once

// Direct codec APIs only. The driver owns clocks, caller buffers and dlopen.
#include "../../adapters/zstd_frame/vendor/zstd/lib/zstd.h"
#include "../../adapters/lz4_frame/vendor/lz4/lib/lz4frame.h"
#include "../../adapters/snappy_raw/vendor/snappy/snappy.h"
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <dlfcn.h>
#include <initializer_list>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>

namespace tsbench_native {
struct EncodedSize { std::size_t head, tail; };

namespace core_detail {
struct SymbolUnavailable : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// The Python bridge emits a flat, canonical object of integer/bool parameters.
// Reject ambiguous keys/types instead of silently benchmarking another config.
class Parameters {
    std::map<std::string, std::string> values_;
public:
    explicit Parameters(const std::string& json) {
        std::size_t at = 0;
        auto space = [&] { while (at < json.size() && std::isspace(static_cast<unsigned char>(json[at]))) ++at; };
        auto character = [&](char c) {
            space();
            if (at >= json.size() || json[at++] != c) throw std::invalid_argument("invalid direct codec JSON configuration");
        };
        character('{'); space();
        if (at < json.size() && json[at] != '}') {
            for (;;) {
                character('"'); const auto key_at = at;
                while (at < json.size() && (std::isalnum(static_cast<unsigned char>(json[at])) || json[at] == '_')) ++at;
                if (at == key_at) throw std::invalid_argument("invalid direct codec configuration key");
                const auto key = json.substr(key_at, at - key_at); character('"'); character(':'); space();
                const auto value_at = at;
                if (json.compare(at, 4, "true") == 0) at += 4;
                else if (json.compare(at, 5, "false") == 0) at += 5;
                else {
                    if (at < json.size() && json[at] == '-') ++at;
                    const auto digits_at = at;
                    while (at < json.size() && json[at] >= '0' && json[at] <= '9') ++at;
                    if (at == digits_at || (at - digits_at > 1 && json[digits_at] == '0'))
                        throw std::invalid_argument("direct codec configuration needs integer/bool values");
                }
                if (!values_.emplace(key, json.substr(value_at, at - value_at)).second)
                    throw std::invalid_argument("duplicate direct codec configuration key");
                space();
                if (at >= json.size()) throw std::invalid_argument("truncated direct codec configuration");
                if (json[at] != ',') break;
                ++at;
            }
        }
        character('}'); space();
        if (at != json.size()) throw std::invalid_argument("trailing direct codec configuration data");
    }
    bool empty() const { return values_.empty(); }
    void keys(std::initializer_list<const char*> required) const {
        if (values_.size() != required.size()) throw std::invalid_argument("incomplete or unknown direct codec configuration");
        for (auto key : required) if (!values_.count(key)) throw std::invalid_argument("missing direct codec configuration key");
    }
    int integer(const char* key, int minimum, int maximum) const {
        const auto& value = values_.at(key);
        std::size_t consumed = 0; long long result;
        try { result = std::stoll(value, &consumed, 10); }
        catch (...) { throw std::invalid_argument(std::string("invalid integer parameter: ") + key); }
        if (consumed != value.size() || result < minimum || result > maximum)
            throw std::invalid_argument(std::string("out-of-range integer parameter: ") + key);
        return static_cast<int>(result);
    }
    bool boolean(const char* key) const {
        const auto& value = values_.at(key);
        if (value != "true" && value != "false") throw std::invalid_argument(std::string("invalid bool parameter: ") + key);
        return value == "true";
    }
};

template<class F> F symbol(void* library, const char* name) {
    dlerror(); void* raw = dlsym(library, name); const char* error = dlerror();
    if (error || !raw) throw SymbolUnavailable(std::string("unavailable native codec symbol: ") + name);
    static_assert(sizeof(F) == sizeof(raw), "POSIX function pointer representation required");
    F result; std::memcpy(&result, &raw, sizeof(result)); return result;
}
inline std::size_t add(std::size_t a, std::size_t b) {
    if (a > std::numeric_limits<std::size_t>::max() - b) throw std::runtime_error("native output bound overflow");
    return a + b;
}
} // namespace core_detail

class Core {
    enum class Kind { raw, zstd, lz4, snappy } kind_;
    core_detail::Parameters parameters_;
    bool encoder_ready_ = false, decoder_ready_ = false;
    int level_ = 0;
    bool checksum_ = false;
    LZ4F_preferences_t lz4_preferences_{};
    ZSTD_CCtx* zstd_encoder_ = nullptr;
    ZSTD_DCtx* zstd_decoder_ = nullptr;
    LZ4F_cctx* lz4_encoder_ = nullptr;
    LZ4F_dctx* lz4_decoder_ = nullptr;
    std::uint8_t dummy_{};

    decltype(&ZSTD_createCCtx) zstd_create_encoder_{};
    decltype(&ZSTD_freeCCtx) zstd_free_encoder_{};
    decltype(&ZSTD_createDCtx) zstd_create_decoder_{};
    decltype(&ZSTD_freeDCtx) zstd_free_decoder_{};
    decltype(&ZSTD_CCtx_setParameter) zstd_parameter_{};
    decltype(&ZSTD_compressBound) zstd_bound_{};
    decltype(&ZSTD_compress2) zstd_encode_{};
    decltype(&ZSTD_decompressDCtx) zstd_decode_{};
    decltype(&ZSTD_isError) zstd_error_{};
    decltype(&ZSTD_getErrorName) zstd_error_name_{};
    decltype(&LZ4F_createCompressionContext) lz4_create_encoder_{};
    decltype(&LZ4F_freeCompressionContext) lz4_free_encoder_{};
    decltype(&LZ4F_createDecompressionContext) lz4_create_decoder_{};
    decltype(&LZ4F_freeDecompressionContext) lz4_free_decoder_{};
    decltype(&LZ4F_compressBound) lz4_bound_{};
    decltype(&LZ4F_compressBegin) lz4_begin_{};
    decltype(&LZ4F_compressUpdate) lz4_update_{};
    decltype(&LZ4F_compressEnd) lz4_end_{};
    decltype(&LZ4F_decompress) lz4_decode_{};
    decltype(&LZ4F_resetDecompressionContext) lz4_reset_decoder_{};
    decltype(&LZ4F_isError) lz4_error_{};
    decltype(&LZ4F_getErrorName) lz4_error_name_{};
    using SnappyBound = std::size_t (*)(std::size_t);
    using SnappyEncode = void (*)(const char*, std::size_t, char*, std::size_t*);
    using SnappyDecode = bool (*)(const char*, std::size_t, char*);
    using SnappyLength = bool (*)(const char*, std::size_t, std::size_t*);
    SnappyBound snappy_bound_{};
    SnappyEncode snappy_encode_{};
    SnappyDecode snappy_decode_{};
    SnappyLength snappy_length_{};

    std::size_t zstd_checked(std::size_t value) const {
        if (zstd_error_(value)) throw std::runtime_error(std::string("Zstd: ") + zstd_error_name_(value));
        return value;
    }
    std::size_t lz4_checked(std::size_t value) const {
        if (lz4_error_(value)) throw std::runtime_error(std::string("LZ4 frame: ") + lz4_error_name_(value));
        return value;
    }
    void needs_parameters() const {
        if (kind_ != Kind::raw && parameters_.empty()) throw std::invalid_argument("encoder requires complete direct codec configuration");
    }
public:
    Core(const std::string& abi, void* library, const std::string& json)
        : kind_(abi == "raw" ? Kind::raw : abi == "zstd" ? Kind::zstd : abi == "lz4" ? Kind::lz4 : Kind::snappy), parameters_(json) {
        if ((kind_ != Kind::raw && !library) || (abi != "raw" && abi != "zstd" && abi != "lz4" && abi != "snappy"))
            throw std::invalid_argument("unknown direct codec ABI");
        if (kind_ == Kind::raw) {
            parameters_.keys({});
        } else if (kind_ == Kind::zstd) {
            if (!parameters_.empty()) {
                parameters_.keys({"compression_level", "content_checksum"});
                level_ = parameters_.integer("compression_level", -5, 22);
                checksum_ = parameters_.boolean("content_checksum");
            }
#define TS_ZSTD(member, name) member = core_detail::symbol<decltype(member)>(library, name)
            TS_ZSTD(zstd_create_encoder_, "ZSTD_createCCtx"); TS_ZSTD(zstd_free_encoder_, "ZSTD_freeCCtx");
            TS_ZSTD(zstd_create_decoder_, "ZSTD_createDCtx"); TS_ZSTD(zstd_free_decoder_, "ZSTD_freeDCtx");
            TS_ZSTD(zstd_parameter_, "ZSTD_CCtx_setParameter"); TS_ZSTD(zstd_bound_, "ZSTD_compressBound");
            TS_ZSTD(zstd_encode_, "ZSTD_compress2"); TS_ZSTD(zstd_decode_, "ZSTD_decompressDCtx");
            TS_ZSTD(zstd_error_, "ZSTD_isError"); TS_ZSTD(zstd_error_name_, "ZSTD_getErrorName");
#undef TS_ZSTD
        } else if (kind_ == Kind::lz4) {
            if (!parameters_.empty()) {
                parameters_.keys({"compression_level", "block_size_id", "block_mode", "content_checksum", "block_checksum"});
                lz4_preferences_.compressionLevel = parameters_.integer("compression_level", 0, 12);
                lz4_preferences_.frameInfo.blockSizeID = static_cast<LZ4F_blockSizeID_t>(parameters_.integer("block_size_id", 4, 7));
                lz4_preferences_.frameInfo.blockMode = parameters_.integer("block_mode", 0, 1) ? LZ4F_blockLinked : LZ4F_blockIndependent;
                lz4_preferences_.frameInfo.contentChecksumFlag = parameters_.boolean("content_checksum") ? LZ4F_contentChecksumEnabled : LZ4F_noContentChecksum;
                lz4_preferences_.frameInfo.blockChecksumFlag = parameters_.boolean("block_checksum") ? LZ4F_blockChecksumEnabled : LZ4F_noBlockChecksum;
            }
#define TS_LZ4(member, name) member = core_detail::symbol<decltype(member)>(library, name)
            TS_LZ4(lz4_create_encoder_, "LZ4F_createCompressionContext"); TS_LZ4(lz4_free_encoder_, "LZ4F_freeCompressionContext");
            TS_LZ4(lz4_create_decoder_, "LZ4F_createDecompressionContext"); TS_LZ4(lz4_free_decoder_, "LZ4F_freeDecompressionContext");
            TS_LZ4(lz4_bound_, "LZ4F_compressBound"); TS_LZ4(lz4_begin_, "LZ4F_compressBegin");
            TS_LZ4(lz4_update_, "LZ4F_compressUpdate"); TS_LZ4(lz4_end_, "LZ4F_compressEnd");
            TS_LZ4(lz4_decode_, "LZ4F_decompress"); TS_LZ4(lz4_reset_decoder_, "LZ4F_resetDecompressionContext");
            TS_LZ4(lz4_error_, "LZ4F_isError"); TS_LZ4(lz4_error_name_, "LZ4F_getErrorName");
#undef TS_LZ4
        } else {
            if (!parameters_.empty()) {
                parameters_.keys({"compression_level", "content_checksum"});
                parameters_.integer("compression_level", 1, 1);
                if (parameters_.boolean("content_checksum")) throw std::invalid_argument("Snappy raw has no checksum parameter");
            }
            // Explicitly pin the existing C++ size_t ABI. Missing symbols fail;
            // there is no fallback through the framework's tscb_* wrappers.
            if (sizeof(std::size_t) != 8) throw std::runtime_error("Snappy direct entry requires the recorded 64-bit size_t ABI");
            snappy_bound_ = core_detail::symbol<SnappyBound>(library, "_ZN6snappy19MaxCompressedLengthEm");
            snappy_encode_ = core_detail::symbol<SnappyEncode>(library, "_ZN6snappy11RawCompressEPKcmPcPm");
            snappy_decode_ = core_detail::symbol<SnappyDecode>(library, "_ZN6snappy13RawUncompressEPKcmPc");
            snappy_length_ = core_detail::symbol<SnappyLength>(library, "_ZN6snappy21GetUncompressedLengthEPKcmPm");
        }
    }
    Core(const Core&) = delete;
    Core& operator=(const Core&) = delete;
    ~Core() { destroy_encoder(); destroy_decoder(); }

    void create_encoder() {
        if (encoder_ready_) throw std::runtime_error("encoder context already exists");
        needs_parameters();
        if (kind_ == Kind::zstd) {
            zstd_encoder_ = zstd_create_encoder_();
            if (!zstd_encoder_) throw std::runtime_error("Zstd encoder allocation failed");
            try {
                zstd_checked(zstd_parameter_(zstd_encoder_, ZSTD_c_compressionLevel, level_));
                zstd_checked(zstd_parameter_(zstd_encoder_, ZSTD_c_nbWorkers, 0));
                zstd_checked(zstd_parameter_(zstd_encoder_, ZSTD_c_contentSizeFlag, 1));
                zstd_checked(zstd_parameter_(zstd_encoder_, ZSTD_c_checksumFlag, checksum_ ? 1 : 0));
                zstd_checked(zstd_parameter_(zstd_encoder_, ZSTD_c_dictIDFlag, 0));
            } catch (...) { zstd_free_encoder_(zstd_encoder_); zstd_encoder_ = nullptr; throw; }
        } else if (kind_ == Kind::lz4) {
            lz4_checked(lz4_create_encoder_(&lz4_encoder_, LZ4F_VERSION));
            if (!lz4_encoder_) throw std::runtime_error("LZ4 encoder allocation failed");
        }
        // Snappy has no public reusable context. Its internal workspace work
        // remains inside RawCompress even for prepared caller buffers.
        encoder_ready_ = true;
    }
    void destroy_encoder() noexcept {
        if (zstd_encoder_) { zstd_free_encoder_(zstd_encoder_); zstd_encoder_ = nullptr; }
        if (lz4_encoder_) { lz4_free_encoder_(lz4_encoder_); lz4_encoder_ = nullptr; }
        encoder_ready_ = false;
    }
    void create_decoder() {
        if (decoder_ready_) throw std::runtime_error("decoder context already exists");
        if (kind_ == Kind::zstd) {
            zstd_decoder_ = zstd_create_decoder_();
            if (!zstd_decoder_) throw std::runtime_error("Zstd decoder allocation failed");
        } else if (kind_ == Kind::lz4) {
            lz4_checked(lz4_create_decoder_(&lz4_decoder_, LZ4F_VERSION));
            if (!lz4_decoder_) throw std::runtime_error("LZ4 decoder allocation failed");
        }
        decoder_ready_ = true;
    }
    void destroy_decoder() noexcept {
        if (zstd_decoder_) { zstd_free_decoder_(zstd_decoder_); zstd_decoder_ = nullptr; }
        if (lz4_decoder_) { lz4_free_decoder_(lz4_decoder_); lz4_decoder_ = nullptr; }
        decoder_ready_ = false;
    }
    std::size_t bound(std::size_t bytes) {
        needs_parameters();
        if (kind_ == Kind::raw) return bytes;
        if (kind_ == Kind::zstd) return zstd_checked(zstd_bound_(bytes));
        if (kind_ == Kind::lz4) return core_detail::add(LZ4F_HEADER_SIZE_MAX,
            core_detail::add(lz4_checked(lz4_bound_(bytes, &lz4_preferences_)), lz4_checked(lz4_bound_(0, &lz4_preferences_))));
        if (bytes > UINT32_MAX) throw std::invalid_argument("Snappy input exceeds its stream length contract");
        const auto result = snappy_bound_(bytes);
        if (result < bytes) throw std::runtime_error("Snappy bound overflow");
        return result;
    }
    EncodedSize encode(const std::uint8_t* input, std::size_t bytes, std::uint8_t* output, std::size_t capacity) {
        if (!encoder_ready_ || (!input && bytes) || (!output && capacity)) throw std::invalid_argument("invalid direct encoder arguments");
        if (!input) input = &dummy_;
        if (!output) output = &dummy_;
        if (kind_ == Kind::raw) {
            if (bytes > capacity) throw std::runtime_error("raw-store output capacity exceeded");
            if (bytes) std::memcpy(output, input, bytes);
            return {bytes, 0};
        }
        if (kind_ == Kind::zstd) {
            // compress2 always starts and completes a new frame. No previous
            // object's input history/dictionary is inherited by workspace reuse.
            return {zstd_checked(zstd_encode_(zstd_encoder_, output, capacity, input, bytes)), 0};
        }
        if (kind_ == Kind::lz4) {
            lz4_preferences_.frameInfo.contentSize = bytes;
            const auto header = lz4_checked(lz4_begin_(lz4_encoder_, output, capacity, &lz4_preferences_));
            if (header > capacity) throw std::runtime_error("LZ4 header exceeds capacity");
            const auto body = lz4_checked(lz4_update_(lz4_encoder_, output + header, capacity - header, input, bytes, nullptr));
            if (body > capacity - header) throw std::runtime_error("LZ4 body exceeds capacity");
            const auto head = header + body;
            const auto tail = lz4_checked(lz4_end_(lz4_encoder_, output + head, capacity - head, nullptr));
            if (tail > capacity - head) throw std::runtime_error("LZ4 finish exceeds capacity");
            return {head, tail};
        }
        const auto required = bound(bytes);
        if (capacity < required) throw std::runtime_error("Snappy encoder capacity below native bound");
        std::size_t written = 0;
        snappy_encode_(reinterpret_cast<const char*>(input), bytes, reinterpret_cast<char*>(output), &written);
        if (written > capacity) throw std::runtime_error("Snappy output exceeds capacity");
        return {written, 0};
    }
    std::size_t decode(const std::uint8_t* input, std::size_t bytes, std::uint8_t* output, std::size_t capacity) {
        if (!decoder_ready_ || (!input && bytes) || (!output && capacity)) throw std::invalid_argument("invalid direct decoder arguments");
        if (!input) input = &dummy_;
        if (!output) output = &dummy_;
        if (kind_ == Kind::raw) {
            if (bytes > capacity) throw std::runtime_error("raw-store output capacity exceeded");
            if (bytes) std::memcpy(output, input, bytes);
            return bytes;
        }
        if (kind_ == Kind::zstd) return zstd_checked(zstd_decode_(zstd_decoder_, output, capacity, input, bytes));
        if (kind_ == Kind::lz4) {
            lz4_reset_decoder_(lz4_decoder_);
            std::size_t read = 0, written = 0;
            for (;;) {
                auto source = bytes - read, destination = capacity - written;
                const auto next = lz4_checked(lz4_decode_(lz4_decoder_, output + written, &destination, input + read, &source, nullptr));
                if (source > bytes - read || destination > capacity - written) throw std::runtime_error("LZ4 decoder exceeded buffer");
                read += source; written += destination;
                if (next == 0) {
                    if (read != bytes) throw std::runtime_error("trailing bytes after LZ4 frame");
                    return written;
                }
                if (source == 0 && destination == 0) throw std::runtime_error("truncated LZ4 frame or insufficient output capacity");
            }
        }
        std::size_t expected = 0;
        // Header-only capacity check is necessary because RawUncompress's API
        // takes no destination capacity. No IsValidCompressedBuffer pre-scan.
        if (!snappy_length_(reinterpret_cast<const char*>(input), bytes, &expected) || expected > capacity)
            throw std::runtime_error("invalid Snappy length or insufficient output capacity");
        if (!snappy_decode_(reinterpret_cast<const char*>(input), bytes, reinterpret_cast<char*>(output)))
            throw std::runtime_error("Snappy RawUncompress failed");
        return expected;
    }
};
} // namespace tsbench_native
