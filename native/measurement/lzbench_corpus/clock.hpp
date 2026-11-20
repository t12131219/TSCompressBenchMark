#pragma once

#include <chrono>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <utility>

namespace lzbench_clock {
using Clock = std::chrono::steady_clock;
inline std::int64_t elapsed(Clock::time_point start) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
}
struct Bucket {
    std::uint64_t calls = 0;
    std::int64_t wall_ns = 0;
    template<class F> decltype(auto) measure(F&& action) {
        struct Span {
            Bucket& bucket;
            Clock::time_point start = Clock::now();
            ~Span() { ++bucket.calls; bucket.wall_ns += elapsed(start); }
        } scope{*this};
        return std::forward<F>(action)();
    }
    void print() const { std::cout << "{\"calls\":" << calls << ",\"wall_ns\":" << wall_ns << '}'; }
};
struct Trial {
    Clock::time_point start;
    std::int64_t first_output_ns = 0;
    std::size_t first_output_bytes = 0;
    Bucket setup, process, framing, cleanup;
    std::ostringstream functional;
    void output(std::size_t bytes) {
        if (bytes && !first_output_bytes) {
            first_output_ns = elapsed(start);
            first_output_bytes = bytes;
        }
    }
    void print() const {
        const auto driver_wall_ns = elapsed(start);
        std::cout << "{\"driver_wall_ns\":" << driver_wall_ns
                  << ",\"first_driver_output_wall_ns\":" << first_output_ns
                  << ",\"first_driver_output_bytes\":" << first_output_bytes << ",\"native_setup\":";
        setup.print();
        std::cout << ",\"native_process\":"; process.print();
        std::cout << ",\"native_framing\":"; framing.print();
        std::cout << ",\"native_cleanup\":"; cleanup.print();
        std::cout << ",\"functional\":" << functional.str() << "}\n";
    }
};
} // namespace lzbench_clock
