// Copyright (c) 2013-2018 InfluxData Inc.
// Copyright (c) 2015 Jason Wilder
// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: MIT
#ifndef TSM_TIMESTAMP_HPP
#define TSM_TIMESTAMP_HPP
#include <cstddef>
#include <cstdint>
#include <vector>
namespace tsm_timestamp {
constexpr std::size_t default_sample_limit=16777216;
enum class Profile { Stream, Batch };
enum class Code { Ok, InvalidArgument, MalformedStream, ResourceLimit, OutputTooSmall, Finalized };
struct Status {Code code=Code::Ok;const char* message="ok";bool ok()const noexcept{return code==Code::Ok;}};
Status encode(const std::int64_t* input,std::size_t count,Profile profile,std::vector<std::uint8_t>* output,std::size_t limit=default_sample_limit)noexcept;
// Exact bound, including complete source framing. Input is immutable.
Status encode_bound(const std::int64_t* input,std::size_t count,Profile profile,std::size_t* bytes,std::size_t limit=default_sample_limit)noexcept;
Status encode_to(const std::int64_t* input,std::size_t count,Profile profile,std::uint8_t* output,std::size_t capacity,std::size_t* written,std::size_t limit=default_sample_limit)noexcept;
class Cursor {
public:
    // Borrows immutable input; a failed reset clears the handle and reports error.
    Status reset(const std::uint8_t* data,std::size_t bytes,std::size_t limit=default_sample_limit)noexcept;
    // Preserves original TimeDecoder.Init(empty) after RLE, including ghost output.
    Status source_init(const std::uint8_t* data,std::size_t bytes,std::size_t limit=default_sample_limit)noexcept;
    Status next(std::int64_t* value,bool* available)noexcept;
    std::size_t count()const noexcept{return total_;}
    std::size_t read_count()const noexcept{return read_;}
    unsigned encoding()const noexcept{return type_;}
private:
    const std::uint8_t* data_=nullptr;
    std::size_t total_=0,read_=0,offset_=0,legacy_n_=0;
    unsigned type_=0,selector_=0,word_index_=0;
    std::uint64_t accumulator_=0,delta_=0,divisor_=1,word_=0;
    bool initialized_=false;
};
Status count_timestamps(const std::uint8_t* data,std::size_t bytes,std::size_t* count,std::size_t limit=default_sample_limit)noexcept;
Status decode(const std::uint8_t* data,std::size_t bytes,std::vector<std::int64_t>* output,std::size_t limit=default_sample_limit)noexcept;
class Encoder {
public:
    explicit Encoder(Profile profile=Profile::Stream,std::size_t limit=default_sample_limit):profile_(profile),limit_(limit<default_sample_limit?limit:default_sample_limit){}
    Status append(std::int64_t value)noexcept;
    Status finish()noexcept;
    Status finalize(std::uint8_t* output,std::size_t capacity,std::size_t* written)noexcept;
    void reset()noexcept;
    Profile profile()const noexcept{return profile_;}
    std::size_t samples()const noexcept{return input_.size();}
    std::size_t final_bits()const noexcept{return bytes_.size()*8;}
    const std::vector<std::uint8_t>& bytes()const noexcept{return bytes_;}
private:
    Profile profile_;std::size_t limit_;bool finalized_=false;
    std::vector<std::int64_t> input_;std::vector<std::uint8_t> bytes_;
};
const char* version()noexcept;
Status capability(const char* identifier,bool* supported)noexcept;
}
#endif
