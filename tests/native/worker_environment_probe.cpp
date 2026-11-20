#include "worker_environment.hpp"
#include <iostream>

int main() {
    const auto begin = tsbench::measurement::worker_checkpoint();
    const auto end = tsbench::measurement::worker_checkpoint();
    std::cout << "{\"begin\":";
    tsbench::measurement::write_worker_checkpoint(std::cout, begin);
    std::cout << ",\"end\":";
    tsbench::measurement::write_worker_checkpoint(std::cout, end);
    std::cout << "}\n";
}
