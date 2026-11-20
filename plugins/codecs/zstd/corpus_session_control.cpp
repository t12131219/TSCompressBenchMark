// Whole-object bounded span driver over the frozen lzbench native session API.
#include "lzbench_extended.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>

namespace {
using namespace lzbench_native;
using Clock = std::chrono::steady_clock;
constexpr std::size_t in_span = 307, out_span = 521;

void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
std::size_t number(std::string_view text) {
    std::size_t result{};
    auto parsed = std::from_chars(text.data(), text.data()+text.size(), result);
    check(parsed.ec == std::errc{} && parsed.ptr == text.data()+text.size() && result > 0,
          "invalid output budget");
    return result;
}
configuration config(std::string_view codec) {
    configuration c;
    if (codec == "zstd") {
        c.codec = LN_ZSTD; c.level = 3;
        c.parameters = {{"workers",0},{"checksum",1}};
    } else {
        check(codec == "xz", "unknown session codec");
        c.codec = LN_XZ; c.level = 1;
        c.parameters = {{"block_size",32768},{"check",4},{"filter0",3},{"filter0_distance",4},
                        {"memory_limit",64<<20},{"threads",1}};
    }
    return c;
}
void transfer(std::string_view codec, bool encode, const char* src, const char* dst, std::size_t budget) {
    std::ifstream input(src,std::ios::binary|std::ios::ate);
    const auto extent = input.tellg();
    check(input && extent > 0,"cannot determine positive source extent");
    const auto size = static_cast<std::size_t>(extent);
    input.seekg(0);
    std::ofstream output(dst,std::ios::binary);
    check(bool(output),"cannot open output");
    session s(config(codec));
    check(s.streaming(),"bound implementation is not a native session");
    reset_worker_stats();
    s.reset(encode);
    std::array<unsigned char,in_span> in;
    std::array<unsigned char,out_span> out;
    std::size_t read=0, consumed=0, produced=0, off=0, end=0, idle=0, calls=0;
    std::size_t first_call=0, first_consumed=0, first_bytes=0, finish_calls=0, partial_input=0, full_output=0, drain=0;
    std::int64_t first_ns=0;
    const auto start=Clock::now();
    while (true) {
        if (off == end && read != size) {
            off=0; end=std::min(in.size(),size-read);
            input.read(reinterpret_cast<char*>(in.data()),end);
            check(bool(input),"short input span");
            read += end;
        }
        const bool finish = read == size;
        const auto offered = end-off;
        auto result = s.process(encode,in.data()+off,offered,out.data(),out.size(),finish);
        check(result.consumed <= offered && result.produced <= out.size() && result.produced <= budget-produced,
              "native call exceeded a span or output budget");
        ++calls;
        partial_input += result.consumed < offered;
        full_output += result.produced == out.size();
        finish_calls += finish;
        drain += !offered && finish;
        off += result.consumed;
        consumed += result.consumed;
        produced += result.produced;
        if (!first_call && result.produced) {
            first_call=calls; first_consumed=consumed; first_bytes=result.produced;
            first_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
        }
        if (result.produced) {
            output.write(reinterpret_cast<const char*>(out.data()),result.produced);
            check(bool(output),"cannot write output span");
        }
        if (result.finished) {
            check(finish && consumed==size && off==end && input.peek()==EOF && !input.bad(),
                  "native finish with trailing input or incomplete source");
            break;
        }
        idle = result.consumed || result.produced ? 0 : idle+1;
        check(idle < 16384,"native session made no progress");
    }
    output.close();
    check(output && first_call && (encode || produced==budget),"session output extent differs");
    auto stats = get_worker_stats();
    std::cout << "{\"input_bytes\":" << consumed << ",\"output_bytes\":" << produced
              << ",\"calls\":" << calls << ",\"finish_calls\":" << finish_calls << ",\"zero_input_finish_calls\":" << drain
              << ",\"partial_input_calls\":" << partial_input << ",\"full_output_calls\":" << full_output
              << ",\"first_output_call\":" << first_call << ",\"first_output_after_consumed_bytes\":" << first_consumed
              << ",\"first_output_bytes\":" << first_bytes << ",\"first_output_driver_wall_ns\":" << first_ns
              << ",\"jobs\":{\"jobs\":" << stats.jobs << ",\"worker_threads\":" << stats.worker_threads
              << ",\"caller_jobs\":" << stats.caller_jobs << "},\"effective_parameters\":{";
    bool comma=false;
    for (const auto& [key,value] : s.effective_parameters()) {
        if (comma) std::cout << ',';
        std::cout << '"' << key << "\":" << value;
        comma=true;
    }
    std::cout << "}}\n";
}
} // namespace

int main(int argc,char** argv) {
    try {
        check(argc==6,"usage: control {zstd|xz} {encode|decode} source dest output-budget");
        const std::string_view direction(argv[2]);
        check(direction=="encode" || direction=="decode","unknown session direction");
        transfer(argv[1],direction=="encode",argv[3],argv[4],number(argv[5]));
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
