#include "collector.hpp"
#include "tsbench/trace_api.h"
#include <atomic>
#include <algorithm>
#include <chrono>
#include <ostream>
#include <stdexcept>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
static_assert(Clock::is_steady);
constexpr unsigned max_threads = 16, max_events = 256;
struct Event { uint64_t parent{}, start{}, end{}; bmk_trace_stage stage{}; };
struct alignas(64) Thread {
    Event events[max_events]{};
    unsigned size{}, dropped{};
    long tid{};
};
Thread buffers[max_threads];
unsigned capacity;
std::atomic<unsigned> claimed{}, overflow{};
std::atomic<bool> enabled{};
std::atomic<uint64_t> root{};
thread_local unsigned slot = max_threads;
thread_local bool assigned = false;
thread_local uint64_t parent{};
uint64_t now() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
}
}

extern "C" uint64_t bmk_trace_begin(enum bmk_trace_stage stage) {
    if (!enabled.load(std::memory_order_acquire)) return 0;
    if (!assigned) {
        slot = claimed.fetch_add(1, std::memory_order_relaxed);
        if (slot < max_threads) buffers[slot].tid = ::syscall(SYS_gettid);
        assigned = true;
    }
    if (slot >= max_threads) { overflow.fetch_add(1, std::memory_order_relaxed); return 0; }
    auto &thread = buffers[slot];
    if (thread.size >= capacity) { ++thread.dropped; return 0; }
    const auto id = uint64_t(slot) * max_events + ++thread.size;
    auto &event = thread.events[thread.size - 1];
    event = {parent ? parent : root.load(std::memory_order_acquire), now(), 0, stage};
    parent = id;
    if (stage == BMK_TRACE_OPERATION) root.store(id, std::memory_order_release);
    return id;
}

extern "C" void bmk_trace_end(uint64_t id) {
    if (!id) return;
    auto &thread = buffers[slot];
    if (parent != id) { ++thread.dropped; return; }
    auto &event = thread.events[(id - 1) % max_events];
    event.end = now();
    parent = event.parent && (event.parent - 1) / max_events == slot ? event.parent : 0;
}

void tsbench::trace::start(unsigned n) {
    if (!n || n > max_events || claimed.load()) throw std::invalid_argument("invalid or repeated trace setup");
    capacity = n;
    enabled.store(true, std::memory_order_release);
}
void tsbench::trace::stop() { enabled.store(false, std::memory_order_release); }
void tsbench::trace::dump(std::ostream &out) {
    const auto used = std::min(claimed.load(), max_threads);
    uint64_t dropped = overflow.load();
    bool comma = false;
    out << "{\"capacity_per_thread\":" << capacity << ",\"spans\":[";
    for (unsigned i = 0; i < used; ++i) {
        const auto &t = buffers[i];
        dropped += t.dropped;
        for (unsigned j = 0; j < t.size; ++j) {
            const auto &e = t.events[j];
            if (!e.end) { ++dropped; continue; }
            if (comma) out << ',';
            comma = true;
            out << "{\"span_id\":" << i * max_events + j + 1 << ",\"parent_id\":" << e.parent
                << ",\"thread_id\":" << t.tid << ",\"stage\":" << e.stage
                << ",\"start_ns\":" << e.start << ",\"end_ns\":" << e.end << '}';
        }
    }
    out << "],\"dropped\":" << dropped << '}';
}
