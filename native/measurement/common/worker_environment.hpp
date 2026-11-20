#ifndef TSBENCH_MEASUREMENT_WORKER_ENVIRONMENT_HPP
#define TSBENCH_MEASUREMENT_WORKER_ENVIRONMENT_HPP

// Endpoint evidence from the calling worker thread, outside the codec clock.
// Linux GNU sched_* APIs, not continuous tracking or per-thread accounting.
#include <cerrno>
#include <cstddef>
#include <optional>
#include <ostream>
#include <vector>
#include <sched.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace tsbench::measurement {

struct WorkerCheckpoint {
    long namespace_pid;
    long namespace_tid;
    int cpu;
    std::optional<std::vector<int>> affinity;
};

inline std::optional<std::vector<int>> worker_affinity() {
    // Retry only the undersized-mask error; larger Linux CPU index spaces
    // cannot be represented by a fixed CPU_SETSIZE stack allocation.
    for (int limit = CPU_SETSIZE; limit <= 131072; limit *= 2) {
        const auto bytes = CPU_ALLOC_SIZE(limit);
        cpu_set_t* mask = CPU_ALLOC(limit);
        if (mask == nullptr) return std::nullopt;
        CPU_ZERO_S(bytes, mask);
        const int rc = sched_getaffinity(0, bytes, mask);
        const int err = errno;
        if (rc != 0) {
            CPU_FREE(mask);
            if (err == EINVAL) continue;
            return std::nullopt;
        }
        std::vector<int> ids;
        try {
            for (int cpu = 0; cpu < limit; ++cpu) {
                if (CPU_ISSET_S(cpu, bytes, mask)) ids.push_back(cpu);
            }
        } catch (...) {
            CPU_FREE(mask);
            throw;
        }
        CPU_FREE(mask);
        if (!ids.empty()) return ids;
        return std::nullopt;
    }
    return std::nullopt;
}

inline WorkerCheckpoint worker_checkpoint() {
    return {getpid(), syscall(SYS_gettid), sched_getcpu(), worker_affinity()};
}

inline void write_worker_checkpoint(std::ostream& stream, const WorkerCheckpoint& record) {
    stream << "{\"namespace_pid\":" << record.namespace_pid << ",\"namespace_tid\":" << record.namespace_tid << ",\"cpu\":";
    if (record.cpu >= 0) stream << record.cpu;
    else stream << "null";
    stream << ",\"affinity\":";
    if (!record.affinity) {
        stream << "null";
    } else {
        stream << '[';
        for (std::size_t i = 0; i < record.affinity->size(); ++i) {
            if (i) stream << ',';
            stream << (*record.affinity)[i];
        }
        stream << ']';
    }
    stream << '}';
}

}  // namespace tsbench::measurement
#endif
