// Native repetition driver. File I/O, hashes and quality checks are outside
// the two batch clocks; Python verifies every retained product afterwards.
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "../../native/include/tscb_adapter_v1.h"
#include "../../adapters/completed_rewrites/native/binding.hpp"
#include "core.hpp"
#include "../../native/include/tsbench_core.h"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sched.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace {
using Byte = std::uint8_t;
using Size = std::size_t;
using tsbench_native::EncodedSize;

struct Failure : std::runtime_error {
    std::string stage;
    int native_status;
    Failure(std::string where, std::string message, int code = -1)
        : std::runtime_error(std::move(message)), stage(std::move(where)), native_status(code) {}
};

std::uint64_t now_ns() {
    timespec value{};
    if (clock_gettime(CLOCK_MONOTONIC, &value))
        throw Failure("clock", "clock_gettime(CLOCK_MONOTONIC) failed");
    return static_cast<std::uint64_t>(value.tv_sec) * UINT64_C(1000000000)
        + static_cast<std::uint64_t>(value.tv_nsec);
}

Size add(Size left, Size right) {
    if (right > std::numeric_limits<Size>::max() - left)
        throw Failure("memory_budget", "size addition overflow");
    return left + right;
}

Size multiply(Size left, Size right) {
    if (left && right > std::numeric_limits<Size>::max() / left)
        throw Failure("memory_budget", "size multiplication overflow");
    return left * right;
}

Size integer(const std::string& text, const char* name) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos)
        throw Failure("arguments", std::string(name) + " must be an unsigned decimal integer");
    Size used{};
    unsigned long long value{};
    try { value = std::stoull(text, &used); }
    catch (const std::exception&) { throw Failure("arguments", std::string(name) + " is out of range"); }
    if (used != text.size() || value > std::numeric_limits<Size>::max())
        throw Failure("arguments", std::string(name) + " is out of range");
    return static_cast<Size>(value);
}

struct Options {
    std::string abi, library, codec, input, config_file, model, result_dir;
    std::string mode = "prepared";
    Size output_bytes = 0, loops = 8, warmup = 2, memory_bytes = 256ULL << 20;
    unsigned dtype_code = TSCB_DTYPE_BYTES_V1, order = 0;
    bool zero_finish = false, decode_only = false, probe = false;
    std::vector<Size> shape;
};

Options parse(int argc, char** argv) {
    Options options;
    bool output_seen = false;
    std::vector<std::string> seen;
    for (int index = 1; index < argc; ++index) {
        const std::string key = argv[index];
        if (std::find(seen.begin(), seen.end(), key) != seen.end())
            throw Failure("arguments", "duplicate option: " + key);
        seen.push_back(key);
        if (key == "--decode-only") { options.decode_only = true; continue; }
        if (key == "--probe") { options.probe = true; continue; }
        if (index + 1 >= argc) throw Failure("arguments", "missing value for " + key);
        const std::string value = argv[++index];
        if (key == "--abi") options.abi = value;
        else if (key == "--library") options.library = value;
        else if (key == "--codec") options.codec = value;
        else if (key == "--input") options.input = value;
        else if (key == "--config-file") options.config_file = value;
        else if (key == "--model") options.model = value;
        else if (key == "--result-dir") options.result_dir = value;
        else if (key == "--mode") options.mode = value;
        else if (key == "--output-bytes") { options.output_bytes = integer(value, "output-bytes"); output_seen = true; }
        else if (key == "--loops") options.loops = integer(value, "loops");
        else if (key == "--warmup") options.warmup = integer(value, "warmup");
        else if (key == "--memory-bytes") options.memory_bytes = integer(value, "memory-bytes");
        else if (key == "--order") {
            if (value != "C" && value != "F") throw Failure("arguments", "order must be C or F");
            options.order = value == "F";
        } else if (key == "--dtype-code") {
            const Size code = integer(value, "dtype-code");
            if (code < 1 || code > 11) throw Failure("arguments", "dtype-code must be 1..11");
            options.dtype_code = static_cast<unsigned>(code);
        } else if (key == "--zero-finish") {
            const Size flag = integer(value, "zero-finish");
            if (flag > 1) throw Failure("arguments", "zero-finish must be 0 or 1");
            options.zero_finish = flag != 0;
        } else if (key == "--shape") {
            Size start = 0;
            do {
                const Size stop = value.find(',', start);
                options.shape.push_back(integer(value.substr(start, stop == std::string::npos ? stop : stop - start), "shape"));
                if (stop == std::string::npos) break;
                start = stop + 1;
            } while (true);
        } else throw Failure("arguments", "unknown option: " + key);
    }
    const std::vector<std::string> abis{"raw", "c1", "rw", "zstd", "lz4", "snappy", "core"};
    if (std::find(abis.begin(), abis.end(), options.abi) == abis.end())
        throw Failure("arguments", "abi must be raw, c1, rw, zstd, lz4, snappy or core");
    if (options.codec.empty() || options.result_dir.empty() || (!options.probe && (options.input.empty() || !output_seen)))
        throw Failure("arguments", "codec, input, result-dir and output-bytes are required");
    if (options.abi != "raw" && options.library.empty()) throw Failure("arguments", "library is required");
    if (options.mode != "prepared" && options.mode != "fresh_request")
        throw Failure("arguments", "mode must be prepared or fresh_request");
    if (!options.probe && (!options.loops || options.loops > 1000000 || options.warmup > 1000000))
        throw Failure("arguments", "loops must be 1..1000000 and warmup 0..1000000");
    if (!options.memory_bytes) throw Failure("arguments", "memory-bytes must be positive");
    if (options.shape.size() > TSCB_MAX_RANK_V1)
        throw Failure("arguments", "shape rank exceeds the C1 contract");
    if (options.dtype_code != TSCB_DTYPE_BYTES_V1 && options.shape.empty())
        throw Failure("arguments", "typed C1 buffers require shape");
    if (options.decode_only && (options.loops != 1 || options.warmup != 0))
        throw Failure("arguments", "decode-only requires loops=1 and warmup=0");
    if (options.decode_only && !options.model.empty())
        throw Failure("arguments", "decode-only must not receive an encoder model");
    if (options.probe) { options.loops = 0; options.warmup = 0; }
    return options;
}

struct Free { void operator()(Byte* pointer) const noexcept { std::free(pointer); } };
using Storage = std::unique_ptr<Byte, Free>;

Storage allocate(Size count, bool pretouch) {
    const Size allocation = std::max<Size>(1, count);
    Storage storage(static_cast<Byte*>(std::malloc(allocation)));
    if (!storage) throw Failure("allocation", "caller buffer allocation failed");
    if (pretouch) std::memset(storage.get(), 0, allocation);
    return storage;
}

struct Input {
    Storage storage;
    Size size;
};

Input read_input(const std::string& filename, Size limit) {
    std::ifstream stream(filename, std::ios::binary | std::ios::ate);
    if (!stream) throw Failure("input", "cannot open input file");
    const auto ending = stream.tellg();
    if (ending < 0 || static_cast<std::uintmax_t>(ending) > limit)
        throw Failure("memory_budget", "input exceeds caller memory budget");
    const Size size = static_cast<Size>(ending);
    auto storage = allocate(size, false);
    stream.seekg(0);
    if (size && !stream.read(reinterpret_cast<char*>(storage.get()), static_cast<std::streamsize>(size)))
        throw Failure("input", "input read failed");
    if (stream.peek() != std::char_traits<char>::eof()) throw Failure("input", "input grew while reading");
    return {std::move(storage), size};
}

std::string read_config(const std::string& filename) {
    if (filename.empty()) return "{}";
    auto input = read_input(filename, 65536);
    return {reinterpret_cast<const char*>(input.storage.get()), input.size};
}

template<class Function> Function symbol(void* library, const char* name) {
    dlerror();
    void* found = dlsym(library, name);
    const char* error = dlerror();
    if (error || !found) throw Failure("load_symbol", std::string("missing native symbol: ") + name, 2);
    return reinterpret_cast<Function>(found);
}

struct Library {
    void* handle{};
    explicit Library(const Options& options) {
        if (options.abi == "raw") return;
        handle = dlopen(options.library.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (!handle) { const char* error = dlerror(); throw Failure("load_library", error ? error : "dlopen failed", 2); }
    }
    ~Library() { if (handle) dlclose(handle); }
    Library(const Library&) = delete;
    Library& operator=(const Library&) = delete;
};

Size width(unsigned code) {
    const Size widths[] = {0, 1, 1, 2, 2, 4, 4, 8, 8, 4, 8, 1};
    return widths[code];
}

tscb_buffer_v1 buffer(Byte* data, Size capacity, Size used,
                      unsigned dtype = TSCB_DTYPE_BYTES_V1, const std::vector<Size>& shape = {}) {
    tscb_buffer_v1 result{};
    result.data = data;
    result.capacity_bytes = capacity;
    result.used_bytes = used;
    result.dtype = dtype;
    result.alignment_bytes = 1;
    while (result.alignment_bytes < 64 &&
           reinterpret_cast<std::uintptr_t>(data) % (result.alignment_bytes * 2) == 0)
        result.alignment_bytes *= 2;
    result.ownership = TSCB_OWNERSHIP_BORROWED_V1;
    if (dtype == TSCB_DTYPE_BYTES_V1) {
        result.rank = 1;
        result.shape[0] = used ? used : capacity;
        result.strides_bytes[0] = 1;
    } else {
        result.rank = static_cast<unsigned>(shape.size());
        Size stride = width(dtype);
        for (Size index = shape.size(); index > 0; --index) {
            result.shape[index - 1] = shape[index - 1];
            if (stride > static_cast<Size>(std::numeric_limits<std::int64_t>::max()))
                throw Failure("descriptor", "stride exceeds int64");
            result.strides_bytes[index - 1] = static_cast<std::int64_t>(stride);
            stride = multiply(stride, shape[index - 1]);
        }
        if (stride != capacity) throw Failure("descriptor", "typed shape and byte size differ");
    }
    return result;
}

class Codec {
public:
    virtual ~Codec() = default;
    virtual void create_encoder() = 0;
    virtual void destroy_encoder() = 0;
    virtual void create_decoder() = 0;
    virtual void destroy_decoder() = 0;
    virtual bool caller_encode() const { return true; }
    virtual bool caller_decode() const { return true; }
    virtual void validate_input(const Byte*,Size) {}
    virtual void validate(const Byte*,Size) {}
    virtual Size bound(const Byte*, Size) = 0;
    virtual Size output_capacity(Size bound_bytes) const { return bound_bytes; }
    virtual EncodedSize encode(const Byte*, Size, Byte*, Size) = 0;
    virtual Size decode(const Byte*, Size, Byte*, Size) = 0;
    virtual tsbench_core_result take_encoded_result() { return {}; }
    virtual tsbench_core_result take_decoded_result() { return {}; }
    virtual void release(tsbench_core_result*) {}
    virtual std::string accounting() const { return ""; }
};

class CoreCodec final : public Codec {
    tsbench_native::Core core_;
public:
    CoreCodec(const Options& options, void* library, const std::string& config) try
        : core_(options.abi, library, config) {}
    catch (const tsbench_native::core_detail::SymbolUnavailable& error) {
        throw Failure("load_symbol", error.what(), 2);
    }
    void create_encoder() override { core_.create_encoder(); }
    void destroy_encoder() override { core_.destroy_encoder(); }
    void create_decoder() override { core_.create_decoder(); }
    void destroy_decoder() override { core_.destroy_decoder(); }
    Size bound(const Byte*, Size size) override { return core_.bound(size); }
    EncodedSize encode(const Byte* source, Size size, Byte* output, Size capacity) override {
        return core_.encode(source, size, output, capacity);
    }
    Size decode(const Byte* source, Size size, Byte* output, Size capacity) override {
        return core_.decode(source, size, output, capacity);
    }
};

// The direct plugin operates on exact task bytes. Decoder parameters/models
// are deliberately absent; all algorithm recovery state belongs in its output.
class PluginCoreCodec final : public Codec {
    tsbench_core_config config_{};
    std::string parameters_, model_;
    void *encoder_{}, *decoder_{};
    tsbench_core_result encoded_{}, decoded_{};
    uint32_t storage_{};
    decltype(&tsbench_core_validate) validate_{};
    decltype(&tsbench_core_validate_input) validate_input_{};
    decltype(&tsbench_core_create) create_;
    decltype(&tsbench_core_destroy) destroy_;
    decltype(&tsbench_core_bound) bound_;
    decltype(&tsbench_core_encode) encode_;
    decltype(&tsbench_core_decode) decode_;
    decltype(&tsbench_core_release) release_;
    decltype(&tsbench_core_error) error_;
    void check(int status, void* context, const char* stage) const {
        if (!status) return;
        const char* detail = error_(context);
        throw Failure(stage, detail ? detail : "direct codec failed", status);
    }
public:
    PluginCoreCodec(const Options& options, void* library, const std::string& parameters)
        : parameters_(parameters), model_(options.model),
          create_(symbol<decltype(create_)>(library,"tsbench_core_create")),
          destroy_(symbol<decltype(destroy_)>(library,"tsbench_core_destroy")),
          bound_(symbol<decltype(bound_)>(library,"tsbench_core_bound")),
          encode_(symbol<decltype(encode_)>(library,"tsbench_core_encode")),
          decode_(symbol<decltype(decode_)>(library,"tsbench_core_decode")),
          release_(symbol<decltype(release_)>(library,"tsbench_core_release")),
          error_(symbol<decltype(error_)>(library,"tsbench_core_error")) {
        if (symbol<decltype(&tsbench_core_version)>(library,"tsbench_core_version")()!=1)
            throw Failure("core.identity","direct ABI version differs",2);
        storage_=symbol<decltype(&tsbench_core_storage)>(library,"tsbench_core_storage")();
        if(storage_>3)throw Failure("core.storage","invalid native storage flags");
        validate_=reinterpret_cast<decltype(validate_)>(dlsym(library,"tsbench_core_validate"));
        validate_input_=reinterpret_cast<decltype(validate_input_)>(dlsym(library,"tsbench_core_validate_input"));
        config_.version=1; config_.dtype=options.dtype_code; config_.order=options.order;
        config_.rank=static_cast<uint32_t>(options.shape.size());
        for(Size i=0;i<options.shape.size();++i)config_.shape[i]=options.shape[i];
        config_.parameters_json=parameters_.c_str();config_.model=model_.empty()?nullptr:model_.c_str();
    }
    ~PluginCoreCodec() override {
        release_(&encoded_);release_(&decoded_);
        if(encoder_)destroy_(encoder_);if(decoder_)destroy_(decoder_);
    }
    void create_encoder() override { check(create_(&config_,0,&encoder_),encoder_,"core.encode.create"); }
    void destroy_encoder() override { auto* p=encoder_;encoder_=nullptr;if(p)check(destroy_(p),nullptr,"core.encode.destroy"); }
    void create_decoder() override {
        auto decoder_config=config_;decoder_config.parameters_json="{}";decoder_config.model=nullptr;
        check(create_(&decoder_config,1,&decoder_),decoder_,"core.decode.create");
    }
    void destroy_decoder() override { auto* p=decoder_;decoder_=nullptr;if(p)check(destroy_(p),nullptr,"core.decode.destroy"); }
    bool caller_encode() const override { return storage_&1; }
    bool caller_decode() const override { return storage_&2; }
    void validate_input(const Byte* source,Size size) override {
        if(validate_input_)check(validate_input_(encoder_,source,size),encoder_,"core.input_validation");
    }
    void validate(const Byte* source,Size size) override {
        if(validate_)check(validate_(decoder_,source,size),decoder_,"core.stream_validation");
    }
    Size bound(const Byte* source,Size size) override {
        Size result{};check(bound_(encoder_,source,size,&result),encoder_,"core.encode.bound");return result;
    }
    EncodedSize encode(const Byte* source,Size size,Byte* output,Size capacity) override {
        check(encode_(encoder_,source,size,output,capacity,&encoded_),encoder_,"core.encode");
        if(encoded_.size>encoded_.capacity || (encoded_.size&&!encoded_.data))throw Failure("core.encode","invalid direct result");
        return {encoded_.size,0};
    }
    Size decode(const Byte* source,Size size,Byte* output,Size capacity) override {
        check(decode_(decoder_,source,size,output,capacity,&decoded_),decoder_,"core.decode");
        if(decoded_.size>decoded_.capacity || (decoded_.size&&!decoded_.data))throw Failure("core.decode","invalid direct result");
        return decoded_.size;
    }
    tsbench_core_result take_encoded_result() override { auto value=encoded_;encoded_={};return value; }
    tsbench_core_result take_decoded_result() override { auto value=decoded_;decoded_={};return value; }
    void release(tsbench_core_result* value) override { release_(value); }
};

class RawCodec final : public Codec {
public:
    void create_encoder() override {}
    void destroy_encoder() override {}
    void create_decoder() override {}
    void destroy_decoder() override {}
    Size bound(const Byte*, Size size) override { return size; }
    EncodedSize encode(const Byte* source, Size size, Byte* output, Size capacity) override {
        if (capacity < size) throw Failure("raw.encode", "raw destination too small", 3);
        if (size) std::memcpy(output, source, size);
        return {size, 0};
    }
    Size decode(const Byte* source, Size size, Byte* output, Size capacity) override {
        if (capacity != size) throw Failure("raw.decode", "raw output length differs", 3);
        if (size) std::memcpy(output, source, size);
        return size;
    }
};

class C1Codec final : public Codec {
    const Options& options_;
    std::string config_;
    tscb_codec_handle_v1* encoder_{};
    tscb_codec_handle_v1* decoder_{};
    decltype(&tscb_create) create_;
    decltype(&tscb_destroy) destroy_;
    decltype(&tscb_reset) reset_;
    decltype(&tscb_compress_bound) bound_;
    decltype(&tscb_compress) encode_;
    decltype(&tscb_finalize) finish_;
    decltype(&tscb_decompress) decode_;
    decltype(&tscb_get_last_error) error_;
    decltype(&tscb_get_accounting_json) accounting_;

    void check(tscb_status_v1 status, tscb_codec_handle_v1* handle, const char* where) const {
        if (status == TSCB_STATUS_OK_V1) return;
        const char* message = nullptr;
        std::uint64_t length{};
        std::string detail = "native C1 status " + std::to_string(status);
        if (handle && error_(handle, &message, &length) == 0 && message && length <= 65536)
            detail += ": " + std::string(message, static_cast<Size>(length));
        throw Failure(where, detail, static_cast<int>(status));
    }

    void create(tscb_codec_handle_v1*& handle, const char* where) {
        if (handle) throw Failure(where, "native handle already exists");
        const auto status = create_(config_.data(), config_.size(), &handle);
        check(status, handle, where);
        if (!handle) throw Failure(where, "create returned a null handle");
    }

    void destroy(tscb_codec_handle_v1*& handle, const char* where) {
        if (!handle) return;
        const auto status = destroy_(handle);
        handle = nullptr;
        check(status, nullptr, where);
    }

public:
    C1Codec(const Options& options, void* library, std::string config)
        : options_(options), config_(std::move(config)),
          create_(symbol<decltype(create_)>(library, "tscb_create")),
          destroy_(symbol<decltype(destroy_)>(library, "tscb_destroy")),
          reset_(symbol<decltype(reset_)>(library, "tscb_reset")),
          bound_(symbol<decltype(bound_)>(library, "tscb_compress_bound")),
          encode_(symbol<decltype(encode_)>(library, "tscb_compress")),
          finish_(symbol<decltype(finish_)>(library, "tscb_finalize")),
          decode_(symbol<decltype(decode_)>(library, "tscb_decompress")),
          error_(symbol<decltype(error_)>(library, "tscb_get_last_error")),
          accounting_(symbol<decltype(accounting_)>(library, "tscb_get_accounting_json")) {
        if (symbol<decltype(&tscb_get_abi_version)>(library, "tscb_get_abi_version")() != 1)
            throw Failure("c1.identity", "C1 ABI version differs", 6);
        const char* manifest{};
        std::uint64_t length{};
        check(symbol<decltype(&tscb_get_manifest_json)>(library, "tscb_get_manifest_json")(&manifest, &length),
              nullptr, "c1.manifest");
        const std::string expected = options.codec == "simdcomp-u32" ? "simdcomp-source-u32" : options.codec;
        if (!manifest || length > 65536 ||
            std::string(manifest, static_cast<Size>(length)).find("\"algorithm\":\"" + expected + "\"") == std::string::npos)
            throw Failure("c1.identity", "native C1 algorithm identity differs", 6);
    }
    ~C1Codec() override { if (encoder_) destroy_(encoder_); if (decoder_) destroy_(decoder_); }
    void create_encoder() override { create(encoder_, "c1.encode.create"); }
    void destroy_encoder() override { destroy(encoder_, "c1.encode.destroy"); }
    void create_decoder() override { create(decoder_, "c1.decode.create"); }
    void destroy_decoder() override { destroy(decoder_, "c1.decode.destroy"); }
    Size bound(const Byte* source, Size size) override {
        auto input = buffer(const_cast<Byte*>(source), size, size, options_.dtype_code, options_.shape);
        std::uint64_t result{};
        check(bound_(encoder_, &input, &result), encoder_, "c1.encode.bound");
        if (result > std::numeric_limits<Size>::max()) throw Failure("c1.encode.bound", "bound exceeds size_t", 2);
        return static_cast<Size>(result);
    }
    Size output_capacity(Size bound_bytes) const override {
        return options_.zero_finish ? bound_bytes : multiply(bound_bytes, 2);
    }
    EncodedSize encode(const Byte* source, Size size, Byte* output, Size capacity) override {
        check(reset_(encoder_, 0), encoder_, "c1.encode.reset");
        auto input = buffer(const_cast<Byte*>(source), size, size, options_.dtype_code, options_.shape);
        const Size head_capacity = options_.zero_finish ? capacity : capacity / 2;
        auto head = buffer(output, head_capacity, 0);
        check(encode_(encoder_, &input, &head), encoder_, "c1.encode.compress");
        if (head.used_bytes > head_capacity) throw Failure("c1.encode.compress", "encoder exceeded capacity");
        const Size tail_capacity = options_.zero_finish ? 0 : head_capacity;
        auto tail = buffer(output + head.used_bytes, tail_capacity, 0);
        check(finish_(encoder_, &tail), encoder_, "c1.encode.finalize");
        if (tail.used_bytes > tail_capacity) throw Failure("c1.encode.finalize", "finalize exceeded capacity");
        return {static_cast<Size>(head.used_bytes), static_cast<Size>(tail.used_bytes)};
    }
    Size decode(const Byte* source, Size size, Byte* output, Size capacity) override {
        check(reset_(decoder_, 0), decoder_, "c1.decode.reset");
        auto input = buffer(const_cast<Byte*>(source), size, size);
        auto decoded = buffer(output, capacity, 0, options_.dtype_code, options_.shape);
        check(decode_(decoder_, &input, &decoded), decoder_, "c1.decode.decompress");
        if (decoded.used_bytes > capacity) throw Failure("c1.decode.decompress", "decoder exceeded capacity");
        return static_cast<Size>(decoded.used_bytes);
    }
    std::string accounting() const override {
        if (!encoder_) return "";
        const char* text{};
        std::uint64_t length{};
        if (accounting_(encoder_, &text, &length) != 0 || !text || length > 65536) return "";
        return {text, static_cast<Size>(length)};
    }
};

std::uint64_t load_le(const Byte* data, unsigned count) {
    std::uint64_t value{};
    for (unsigned index = 0; index < count; ++index) value |= std::uint64_t(data[index]) << (index * 8);
    return value;
}

class RwCodec final : public Codec {
    RwConfig config_{};
    std::string model_;
    decltype(&rw_bound) bound_;
    decltype(&rw_encode) encode_;
    decltype(&rw_decode) decode_;
public:
    RwCodec(const Options& options, void* library, const std::string& config)
        : model_(options.model), bound_(symbol<decltype(bound_)>(library, "rw_bound")),
          encode_(symbol<decltype(encode_)>(library, "rw_encode")),
          decode_(symbol<decltype(decode_)>(library, "rw_decode")) {
        if (symbol<decltype(&rw_version)>(library, "rw_version")() != 1)
            throw Failure("rw.identity", "RW ABI version differs", 6);
        const char* algorithm = symbol<decltype(&rw_algorithm)>(library, "rw_algorithm")();
        if (!algorithm || options.codec != algorithm) throw Failure("rw.identity", "RW algorithm identity differs", 6);
        if (options.decode_only || options.probe) return;
        if (config.size() != 64) throw Failure("rw.config", "RW encoder config must contain exactly 64 LE bytes");
        static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559, "RW requires IEEE754 binary64");
        const auto* data = reinterpret_cast<const Byte*>(config.data());
        config_.rows = load_le(data, 8); config_.columns = load_le(data + 8, 8);
        config_.a = static_cast<std::uint32_t>(load_le(data + 16, 4));
        config_.b = static_cast<std::uint32_t>(load_le(data + 20, 4));
        config_.c = static_cast<std::uint32_t>(load_le(data + 24, 4));
        config_.d = static_cast<std::uint32_t>(load_le(data + 28, 4));
        config_.seed = static_cast<std::uint32_t>(load_le(data + 32, 4));
        config_.mode = static_cast<std::uint32_t>(load_le(data + 36, 4));
        auto bits = load_le(data + 40, 8); std::memcpy(&config_.x, &bits, 8);
        bits = load_le(data + 48, 8); std::memcpy(&config_.y, &bits, 8);
        bits = load_le(data + 56, 8); std::memcpy(&config_.z, &bits, 8);
        config_.model = model_.c_str();
        if (config_.columns != 1) throw Failure("rw.config", "native RW binding accepts one stream; multi-column composition is auxiliary", 2);
    }
    void create_encoder() override {}
    void destroy_encoder() override {}
    void create_decoder() override {}
    void destroy_decoder() override {}
    Size bound(const Byte* source, Size size) override {
        Size result{};
        char error[2048]{};
        const int status = bound_(&config_, source, size, &result, error, sizeof(error));
        if (status) throw Failure("rw.encode.bound", error, status);
        return result;
    }
    EncodedSize encode(const Byte* source, Size size, Byte* output, Size capacity) override {
        Size result{};
        char error[2048]{};
        const int status = encode_(&config_, source, size, output, capacity, &result, error, sizeof(error));
        if (status) throw Failure("rw.encode", error, status);
        if (result > capacity) throw Failure("rw.encode", "RW encoder exceeded capacity");
        return {result, 0};
    }
    Size decode(const Byte* source, Size size, Byte* output, Size capacity) override {
        Size result{};
        char error[2048]{};
        const int status = decode_(source, size, output, capacity, &result, error, sizeof(error));
        if (status) throw Failure("rw.decode", error, status);
        if (result > capacity) throw Failure("rw.decode", "RW decoder exceeded capacity");
        return result;
    }
};

struct Slot {
    Storage payload, restored;
    tsbench_core_result encoded_result{}, decoded_result{};
    const Byte* encoded_data() const { return encoded_result.data ? encoded_result.data : payload.get(); }
    const Byte* decoded_data() const { return decoded_result.data ? decoded_result.data : restored.get(); }
    Size capacity{}, bound{}, head{}, tail{}, used{}, restored_used{};
};

struct Report {
    std::string status = "error", stage = "arguments", error, accounting, maps_path;
    int native_status = -1;
    std::uint64_t setup_ns{}, warmup_ns{}, encode_ns{}, decode_ns{}, input_validation_ns{}, stream_validation_ns{};
    bool caller_encode=true, caller_decode=true;
    Size input_bytes{}, caller_memory_bytes{};
    std::vector<Slot> slots;
};

void write_file(const std::filesystem::path& path, const Byte* data, Size count) {
    const int descriptor = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (descriptor < 0) throw Failure("save", "cannot create a new result file: " + path.string());
    Size at{};
    while (at < count) {
        const auto result = write(descriptor, data + at, count - at);
        if (result < 0 && errno == EINTR) continue;
        if (result <= 0) { close(descriptor); throw Failure("save", "result write failed: " + path.string()); }
        at += static_cast<Size>(result);
    }
    if (close(descriptor)) throw Failure("save", "result close failed: " + path.string());
}

std::string product_name(const char* prefix, const char* kind, Size index) {
    std::ostringstream name;
    name << prefix << kind << '-' << std::setw(6) << std::setfill('0') << index << ".bin";
    return name.str();
}

void save_maps(const Options& options, Report& report) {
    std::ifstream stream("/proc/self/maps", std::ios::binary);
    if (!stream) throw Failure("runtime_maps", "/proc/self/maps unavailable");
    const std::string maps((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    const auto path = std::filesystem::path(options.result_dir) / "runtime_maps.txt";
    write_file(path, reinterpret_cast<const Byte*>(maps.data()), maps.size());
    report.maps_path = path.string();
}

void run(const Options& options, Report& report) {
    const auto setup_begin = now_ns();
    report.stage = "setup";
    if (!std::filesystem::exists(options.result_dir)) std::filesystem::create_directories(options.result_dir);
    if (!std::filesystem::is_directory(options.result_dir)) throw Failure("setup", "result-dir is not a directory");
    const std::string config = options.abi == "raw" || (options.abi == "rw" && (options.decode_only || options.probe))
        ? "{}" : read_config(options.config_file);
    Library library(options);
    std::unique_ptr<Codec> codec;
    if (options.abi == "raw") codec = std::make_unique<RawCodec>();
    else if (options.abi == "c1") codec = std::make_unique<C1Codec>(options, library.handle, config);
    else if (options.abi == "rw") codec = std::make_unique<RwCodec>(options, library.handle, config);
    else if (options.abi == "core") codec = std::make_unique<PluginCoreCodec>(options, library.handle, config);
    else codec = std::make_unique<CoreCodec>(options, library.handle, config);
    report.caller_encode=codec->caller_encode();report.caller_decode=codec->caller_decode();
    if (options.probe) {
        save_maps(options, report);
        report.setup_ns = now_ns() - setup_begin;
        report.status = "ok"; report.stage = "probe_complete"; report.native_status = 0;
        return;
    }
    // All native owners must be released while their plugin is still mapped,
    // including exception paths. Report retains only sizes after this scope.
    struct Products {
        Codec& codec; Report& report;
        ~Products() { for(auto& slot:report.slots) {
            codec.release(&slot.encoded_result);codec.release(&slot.decoded_result);
        } }
    } products{*codec,report};
    auto input = read_input(options.input, options.memory_bytes);
    report.input_bytes = input.size;

    const Size count = add(options.loops, options.warmup);
    // Reserve every eventual restored buffer before any encoder allocation.
    // This is a caller-owned buffer budget, not a native-context/RSS bound.
    Size memory = add(std::max<Size>(1, input.size), multiply(count, sizeof(Slot)));
    if(codec->caller_decode())memory = add(memory, multiply(count, std::max<Size>(1, options.output_bytes)));
    if (memory > options.memory_bytes) throw Failure("memory_budget", "input/metadata/restored reservation exceeds caller budget");
    report.slots.resize(count);
    const bool prepared = options.mode == "prepared";
    const auto add_payload = [&](Slot& slot, Size bound_bytes) {
        slot.bound = bound_bytes;
        slot.capacity = codec->output_capacity(bound_bytes);
        if(codec->caller_encode()) {
            const Size next = add(memory, std::max<Size>(1, slot.capacity));
            if (next > options.memory_bytes) throw Failure("memory_budget", "retained caller buffers exceed memory budget");
            slot.payload = allocate(slot.capacity, prepared);
            memory = next;
        }
    };
    if (prepared) {
        if (!options.decode_only) codec->create_encoder();
        codec->create_decoder();
        const Size maximum = options.decode_only ? 0 : codec->bound(input.storage.get(), input.size);
        for (auto& slot : report.slots) {
            if (!options.decode_only) add_payload(slot, maximum);
            if(codec->caller_decode())slot.restored = allocate(options.output_bytes, true);
        }
    }

    if(!options.decode_only) {
        const auto validation_start=now_ns();
        if(!prepared)codec->create_encoder();
        codec->validate_input(input.storage.get(),input.size);
        if(!prepared)codec->destroy_encoder();
        report.input_validation_ns=now_ns()-validation_start;
    }
    const auto validate = [&](Size first,Size last) {
        const auto validation_start=now_ns();
        if(!prepared)codec->create_decoder();
        for(Size i=first;i<last;++i) {
            const auto& slot=report.slots[i];
            codec->validate(options.decode_only?input.storage.get():slot.encoded_data(),
                            options.decode_only?input.size:slot.used);
        }
        if(!prepared)codec->destroy_decoder();
        report.stream_validation_ns+=now_ns()-validation_start;
    };

    const auto encode = [&](Slot& slot) {
        if (!prepared) {
            codec->create_encoder();
            const Size maximum = codec->bound(input.storage.get(), input.size);
            add_payload(slot, maximum);
        }
        const EncodedSize sizes = codec->encode(input.storage.get(), input.size, slot.payload.get(), slot.capacity);
        slot.encoded_result=codec->take_encoded_result();
        if(slot.encoded_result.owner) {
            memory=add(memory,slot.encoded_result.capacity);
            if(memory>options.memory_bytes)throw Failure("memory_budget","retained native output exceeds budget");
        }
        slot.head = sizes.head; slot.tail = sizes.tail; slot.used = add(sizes.head, sizes.tail);
        if (slot.used > (slot.encoded_result.data ? slot.encoded_result.capacity : slot.capacity)) throw Failure("encode.length", "native output exceeds capacity");
        if (!prepared) codec->destroy_encoder();
    };
    const auto decode = [&](Slot& slot) {
        if (!prepared) {
            codec->create_decoder();
            if(codec->caller_decode())slot.restored = allocate(options.output_bytes, false);
        }
        const Byte* source = options.decode_only ? input.storage.get() : slot.encoded_data();
        const Size source_size = options.decode_only ? input.size : slot.used;
        slot.restored_used = codec->decode(source, source_size, slot.restored.get(), options.output_bytes);
        slot.decoded_result=codec->take_decoded_result();
        if(slot.decoded_result.owner) {
            memory=add(memory,slot.decoded_result.capacity);
            if(memory>options.memory_bytes)throw Failure("memory_budget","retained native restored output exceeds budget");
        }
        if (slot.restored_used != options.output_bytes) throw Failure("decode.length", "native restored byte count differs from requested capacity");
        if (!prepared) codec->destroy_decoder();
    };

    const auto warmup_begin = now_ns();
    report.setup_ns = warmup_begin - setup_begin;
    report.stage = "warmup";
    for (Size index = 0; index < options.warmup; ++index) encode(report.slots[index]);
    if(options.warmup)validate(0,options.warmup);
    for (Size index = 0; index < options.warmup; ++index) decode(report.slots[index]);
    report.warmup_ns = now_ns() - warmup_begin;

    if (!options.decode_only) {
        report.stage = "encode";
        const auto begin = now_ns();
        for (Size index = options.warmup; index < count; ++index) encode(report.slots[index]);
        report.encode_ns = now_ns() - begin;
    }
    report.stage = "stream_validation";
    validate(options.warmup,count);
    report.stage = "decode";
    const auto begin = now_ns();
    for (Size index = options.warmup; index < count; ++index) decode(report.slots[index]);
    report.decode_ns = now_ns() - begin;
    report.caller_memory_bytes = memory;
    report.accounting = codec->accounting();
    codec->destroy_encoder();
    codec->destroy_decoder();

    report.stage = "save";
    // Capture maps after lazy-loaded work while the actual codec library is
    // still mapped. Runtime files and every product are written after clocks.
    save_maps(options, report);
    for (Size index = 0; index < count; ++index) {
        const bool warmup = index < options.warmup;
        const char* prefix = warmup ? "warmup-" : "";
        const Size number = warmup ? index : index - options.warmup;
        const auto& slot = report.slots[index];
        if (!options.decode_only)
            write_file(std::filesystem::path(options.result_dir) / product_name(prefix, "payload", number), slot.encoded_data(), slot.used);
        write_file(std::filesystem::path(options.result_dir) / product_name(prefix, "restored", number), slot.decoded_data(), slot.restored_used);
    }
    write_file(std::filesystem::path(options.result_dir) / "input-after.bin", input.storage.get(), input.size);
    report.status = "ok"; report.stage = "complete"; report.native_status = 0;
}

std::string quote(const std::string& value) {
    std::ostringstream output;
    output << '"';
    for (const unsigned char character : value) {
        if (character == '"' || character == '\\') output << '\\' << character;
        else if (character < 32) output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(character) << std::dec;
        else output << character;
    }
    output << '"';
    return output.str();
}

template<class Field> void array(std::ostream& output, const Report& report, Size first, Size count, Field field) {
    output << '[';
    for (Size index = 0; index < count && first + index < report.slots.size(); ++index) {
        if (index) output << ',';
        output << field(report.slots[first + index]);
    }
    output << ']';
}

void print_report(const Options& options, const Report& report) {
    std::cout << "{\"schema\":\"tsbench.native-batch/1\",\"clock\":\"CLOCK_MONOTONIC\",\"status\":" << quote(report.status)
        << ",\"stage\":" << quote(report.stage) << ",\"error\":" << quote(report.error)
        << ",\"native_status\":" << report.native_status << ",\"abi\":" << quote(options.abi)
        << ",\"codec\":" << quote(options.codec) << ",\"mode\":" << quote(options.mode)
        << ",\"decode_only\":" << (options.decode_only ? "true" : "false")
        << ",\"probe_only\":" << (options.probe ? "true" : "false")
        << ",\"iterations\":" << options.loops << ",\"warmup_iterations\":" << options.warmup
        << ",\"setup_ns\":" << report.setup_ns << ",\"warmup_ns\":" << report.warmup_ns
        << ",\"encode_batch_ns\":" << report.encode_ns << ",\"decode_batch_ns\":" << report.decode_ns
        << ",\"input_validation_ns\":" << report.input_validation_ns << ",\"stream_validation_ns\":" << report.stream_validation_ns
        << ",\"caller_encode_buffer\":" << (report.caller_encode?"true":"false") << ",\"caller_decode_buffer\":" << (report.caller_decode?"true":"false")
        << ",\"input_bytes\":" << report.input_bytes << ",\"output_bytes\":" << options.output_bytes
        << ",\"memory_budget_bytes\":" << options.memory_bytes << ",\"caller_memory_bytes\":" << report.caller_memory_bytes
        << ",\"caller_memory_scope\":\"input plus caller buffers, retained native owned result capacities and slot metadata; excludes config, libraries, contexts and transient native allocations\""
        << ",\"native_internal_memory_known\":false,\"retained_output_release_outside_timing\":true"
        << ",\"caller_pages_pretouched\":" << (options.mode == "prepared" ? "true" : "false")
        << ",\"source_and_stream_admission_outside_main_clocks\":true,\"quality_checked_by_driver\":false,\"native_api_internal_work_included\":"
        << (options.abi == "c1" || options.abi == "rw" ? "true" : "false")
        << ",\"batch_clock_count_per_operation\":1,\"python_inside_batch_clock\":false"
        << ",\"encode_batch_clock_count\":" << (options.probe || options.decode_only ? 0 : 1)
        << ",\"decode_batch_clock_count\":" << (options.probe ? 0 : 1)
        << ",\"native_loop_batch\":true,\"measurement_boundary\":"
        << quote(options.abi == "c1" || options.abi == "rw" ? "native_api" : "native_core")
        << ",\"reset_inside_batch_clock\":true,\"accounting_json\":" << quote(report.accounting)
        << ",\"process_pid\":" << getpid() << ",\"parent_pid\":" << getppid()
        << ",\"loader_environment\":{\"LD_PRELOAD\":" << quote(std::getenv("LD_PRELOAD") ? std::getenv("LD_PRELOAD") : "")
        << ",\"LD_LIBRARY_PATH\":" << quote(std::getenv("LD_LIBRARY_PATH") ? std::getenv("LD_LIBRARY_PATH") : "") << "}"
        << ",\"runtime_maps_path\":" << quote(report.maps_path)
        << ",\"output_sizes\":";
    array(std::cout, report, options.warmup, options.loops, [](const Slot& slot) { return slot.used; });
    std::cout << ",\"head_sizes\":";
    array(std::cout, report, options.warmup, options.loops, [](const Slot& slot) { return slot.head; });
    std::cout << ",\"finalize_sizes\":";
    array(std::cout, report, options.warmup, options.loops, [](const Slot& slot) { return slot.tail; });
    std::cout << ",\"bound_sizes\":";
    array(std::cout, report, options.warmup, options.loops, [](const Slot& slot) { return slot.bound; });
    std::cout << ",\"restored_sizes\":";
    array(std::cout, report, options.warmup, options.loops, [](const Slot& slot) { return slot.restored_used; });
    std::cout << ",\"warmup_output_sizes\":";
    array(std::cout, report, 0, options.warmup, [](const Slot& slot) { return slot.used; });
    std::cout << ",\"warmup_restored_sizes\":";
    array(std::cout, report, 0, options.warmup, [](const Slot& slot) { return slot.restored_used; });
    cpu_set_t mask;
    CPU_ZERO(&mask);
    std::cout << ",\"affinity_cpus\":[";
    if (sched_getaffinity(0, sizeof(mask), &mask) == 0) {
        bool comma = false;
        for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) if (CPU_ISSET(cpu, &mask)) {
            if (comma) std::cout << ',';
            std::cout << cpu; comma = true;
        }
    }
    std::cout << "]";
    rlimit limit{};
    std::cout << ",\"rlimit_as\":";
    if (getrlimit(RLIMIT_AS, &limit) == 0) {
        std::cout << "{\"soft_bytes\":";
        if (limit.rlim_cur == RLIM_INFINITY) std::cout << "null"; else std::cout << limit.rlim_cur;
        std::cout << ",\"hard_bytes\":";
        if (limit.rlim_max == RLIM_INFINITY) std::cout << "null"; else std::cout << limit.rlim_max;
        std::cout << '}';
    } else std::cout << "null";
    timespec resolution{};
    std::cout << ",\"clock_resolution_ns\":";
    if (clock_getres(CLOCK_MONOTONIC, &resolution) == 0)
        std::cout << static_cast<std::uint64_t>(resolution.tv_sec) * UINT64_C(1000000000) + static_cast<std::uint64_t>(resolution.tv_nsec);
    else std::cout << "null";
    std::cout << "}\n";
}
} // namespace

int main(int argc, char** argv) {
    Options options;
    Report report;
    try { options = parse(argc, argv); run(options, report); }
    catch (const Failure& failure) {
        report.native_status = failure.native_status;
        report.stage = failure.stage; report.error = failure.what();
        report.status = failure.native_status == 2 ? "unsupported" : "error";
    } catch (const std::exception& error) { report.error = error.what(); }
    catch (...) { report.error = "unknown native driver exception"; }
    print_report(options, report);
    return report.status == "ok" ? 0 : 2;
}
