// Copyright The Prometheus Authors
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause
#ifndef HISTOGRAM_ST_HPP
#define HISTOGRAM_ST_HPP
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace histogram_st {
enum class Kind { Integer, Floating };
enum class Code { Ok, InvalidArgument, MalformedStream, OutputTooSmall, SampleLimit, ResourceLimit, AppendOnly };
struct Status { Code code=Code::Ok; const char* message="ok"; bool ok() const noexcept { return code==Code::Ok; } };
struct Span { std::int32_t offset=0; std::uint32_t length=0; };
// Count/zero/buckets are uint64 values (integer) or binary64 bits (floating).
// Integer buckets store signed adjacent deltas using their modulo64 bit pattern.
struct Sample {
    std::int64_t st=0, timestamp=0;
    std::int32_t schema=0;
    std::uint64_t threshold=0, count=0, zero=0, sum=0;
    std::uint8_t hint=0;
    std::vector<Span> positive_spans, negative_spans;
    std::vector<std::uint64_t> custom, positive, negative;
};
struct AppendResult { Status status; bool new_chunk=false, recoded=false; };
class Cursor {
public:
    Cursor();
    ~Cursor();
    Cursor(Cursor&&) noexcept;
    Cursor& operator=(Cursor&&) noexcept;
    Cursor(const Cursor&)=delete;
    Cursor& operator=(const Cursor&)=delete;
    // Input is borrowed until reset/destruction; caller retains immutable bytes.
    Status reset(Kind kind,const std::uint8_t* data,std::size_t bytes) noexcept;
    Status reset_frame(const std::uint8_t* frame,std::size_t bytes) noexcept;
    // reusable_float_output selects source AtFloatHistogram(non-nil) arithmetic.
    Status next(Sample* sample,bool* available,bool as_float=false,bool reusable_float_output=false) noexcept;
    Status seek(std::int64_t timestamp,Sample* sample,bool* available,bool as_float=false,bool reusable_float_output=false) noexcept;
    std::size_t samples_read() const noexcept;
    std::size_t consumed_bits() const noexcept;
private:
    friend class Chunk;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
class Chunk {
public:
    explicit Chunk(Kind kind);
    ~Chunk();
    Chunk(const Chunk&);
    Chunk& operator=(const Chunk&);
    Chunk(Chunk&&) noexcept;
    Chunk& operator=(Chunk&&) noexcept;
    // Copies and validates bytes, restoring source decoder/appender state.
    Status reset(const std::uint8_t* data,std::size_t bytes) noexcept;
    Status reset_frame(const std::uint8_t* frame,std::size_t bytes) noexcept;
    Status clear() noexcept;
    // On success this object becomes the source's replacement/current chunk.
    // new_chunk tells the caller to retain the previous bytes as another chunk.
    // Caller input and this chunk are unchanged on error.
    AppendResult append(const Sample& sample,bool append_only=false,const Chunk* previous=nullptr) noexcept;
    Status finalize(std::uint8_t* output,std::size_t capacity,std::size_t* written) const noexcept;
    // Self-contained frame: source encoding byte (5/6), BE uint64 payload size,
    // then unchanged source chunk bytes. FinalBits counts this framing.
    Status serialize_frame(std::uint8_t* output,std::size_t capacity,std::size_t* written) const noexcept;
    Status compact() noexcept;
    std::size_t size_bytes() const noexcept;
    std::size_t frame_bytes() const noexcept;
    std::size_t payload_bits() const noexcept;
    std::size_t final_bits() const noexcept;
    std::size_t samples() const noexcept;
    std::uint8_t counter_reset_header() const noexcept;
    Kind kind() const noexcept;
    const std::vector<std::uint8_t>& bytes() const noexcept;
    // Conservative bound includes all old samples if expansion requires recode.
    Status append_bound(const Sample& sample,std::size_t* bytes) const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
const char* version() noexcept;
Status capability(const char* identifier,bool* supported) noexcept;
} // namespace histogram_st
#endif
