// SPDX-License-Identifier: LicenseRef-Local-Research
#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>
#include <stdexcept>
#include <limits>
namespace chimp {
constexpr std::size_t max_values=1048576;
enum class Method : std::uint8_t { Chimp=1, Chimp32=2, ChimpN=3, ChimpNoIndex=4, ChimpN32=5, Fpc=6, Pmc=7, Swing=8, Disjoint=9, Quantized=10, QuantizedFilter2=11 };
struct Config { Method method=Method::Chimp; std::uint32_t history=128; float epsilon=0.1f; };
struct Point { std::int64_t timestamp; float value; };
struct Segment { std::int64_t start,end; double a,b; double a_min=0,a_max=0; float quantized_b=0; };
struct Bits { std::vector<std::uint8_t> bytes; std::size_t meaningful_bits=0; };
std::size_t raw_bound(Config,std::size_t count);
class ChimpEncoder {
 Config cfg_; unsigned width_,log_,threshold_; std::vector<std::uint64_t> history_; std::vector<std::uint32_t> indices_;
 std::uint32_t index_=0,current_=0; unsigned leading_=65; bool first_=true,closed_=false; Bits bits_;
 void put(std::uint64_t,unsigned); void append_word(std::uint64_t);
public:
 explicit ChimpEncoder(Config={}); void add(std::uint64_t raw_bits); Bits finalize(); void reset();
 std::size_t workspace_bytes() const noexcept;
 std::size_t meaningful_bits()const noexcept{return bits_.meaningful_bits;}
 const std::vector<std::uint8_t>& bytes()const noexcept{return bits_.bytes;} std::size_t size() const noexcept {return first_?0:std::size_t(index_)+1;}
};
class ChimpDecoder {
 Config cfg_; unsigned width_,log_,current_=0,leading_=65; bool first_=true,closed_=false;
 std::vector<std::uint8_t> bytes_; std::vector<std::uint64_t> history_; std::uint64_t last_=0;
 std::size_t pos_=0,count_=0; std::uint64_t get(unsigned,std::size_t&) const;
public:
 ChimpDecoder(Config,const std::vector<std::uint8_t>&); bool next(std::uint64_t&);
 void reset(const std::vector<std::uint8_t>&); std::size_t count()const noexcept{return count_;}
};
class SegmentDecoder {
 std::vector<Segment> segments_; std::size_t current_=0; std::uint64_t offset_=0; bool constant_values_=false;
public:
 explicit SegmentDecoder(const std::vector<Segment>&,bool constant_values=false); bool next(Point&); void reset() noexcept {current_=0;offset_=0;}
};
Bits encode_chimp(Config,const std::vector<std::uint64_t>&);
std::vector<std::uint64_t> decode_chimp(Config,const std::vector<std::uint8_t>&);
// FPC translated from Michael Kutschke's 2013 EPL-1.0 Java implementation.
class Fpc {
 std::vector<std::uint64_t> fcm_,dfcm_; std::uint32_t fh_=0,dh_=0; std::uint64_t last_=0; bool closed_=false;
 void update(std::uint64_t); std::uint64_t prediction(unsigned) const;
public:
 Fpc(); static std::uint64_t to_long(const std::vector<std::uint8_t>&); static std::vector<std::uint8_t> to_byte_array(std::uint64_t); void reset(); void finalize() noexcept {closed_=true;}
 std::vector<std::uint8_t> encode(const std::vector<std::uint64_t>&,bool reject_payload_nan=false);
 std::vector<std::uint64_t> decode(const std::vector<std::uint8_t>&,std::size_t count);
 std::size_t workspace_bytes() const noexcept {return (fcm_.capacity()+dfcm_.capacity())*sizeof(std::uint64_t);}
};
std::vector<Segment> filter(Config,const std::vector<Point>&);
std::vector<Point> reconstruct(const std::vector<Segment>&,bool constant_values=false);
struct Quality { bool finite=true; bool within_epsilon=true; double max_absolute_error=0; std::size_t violations=0; };
Quality quality(const std::vector<Point>& input,const std::vector<Point>& output,float epsilon,bool by_index=false);
struct Decoded { Config config; std::vector<std::uint64_t> words; std::vector<Point> points; std::vector<Segment> segments; };
std::vector<std::uint8_t> encode_frame(Config,const std::vector<std::uint64_t>&);
std::vector<std::uint8_t> encode_frame(Config,const std::vector<Point>&,bool require_absolute_bound=false);
Decoded decode_frame(const std::vector<std::uint8_t>&);
std::vector<std::uint8_t> serialize_segments(const std::vector<Segment>&);
std::vector<Segment> parse_segments(const std::vector<std::uint8_t>&);
}
