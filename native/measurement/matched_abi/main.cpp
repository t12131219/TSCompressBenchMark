#include "worker_environment.hpp"
#include <fstream>
#include <iostream>

int tsbench_matched_worker_main(int argc, char** argv);

int main(int argc, char** argv) {
    const auto begin = tsbench::measurement::worker_checkpoint();
    const int result = tsbench_matched_worker_main(argc, argv);
    const auto end = tsbench::measurement::worker_checkpoint();
    // The isolation launcher sets cwd to the worker's private output directory.
    // Keep the witness separate from the ABI worker's unchanged stdout contract.
    std::ofstream out("worker-environment.stdout", std::ios::binary | std::ios::trunc);
    out << "{\"begin\":";
    tsbench::measurement::write_worker_checkpoint(out, begin);
    out << ",\"end\":";
    tsbench::measurement::write_worker_checkpoint(out, end);
    out << "}\n";
    out.close();
    if (!out) {
        std::cerr << "could not publish native environment witness\n";
        return result ? result : 5;
    }
    return result;
}
