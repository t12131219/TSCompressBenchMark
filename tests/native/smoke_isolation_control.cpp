// Test-only worker: check the actual namespace from within the operation and
// exercise real supervisor terminal paths. The normal ABI work is unchanged.
#include <cerrno>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <string_view>
#include <unistd.h>
#include <fcntl.h>

#define main bmk_smoke_normal_main
#include "../../native/worker/worker_main.cpp"
#undef main

int main(int argc, char **argv) {
    namespace fs = std::filesystem;
    if (argc < 5) return 2;
    if (fs::exists("/usr") || fs::exists("/proc") || fs::exists("/home") ||
        fs::exists("/datasets") || fs::exists("/etc/ld.so.cache")) {
        std::cerr << "control: unexpected host filesystem\n";
        return 7;
    }
    const std::string_view op = argv[1], plugin = argv[3];
    size_t files = 0;
    for (const auto &entry : fs::directory_iterator("/inputs")) {
        ++files;
        const auto name = entry.path().filename().string();
        if ((op == "encode" && name != "original.bin" && name != "original.json") ||
            (op == "decode" && name != "frame.bmk")) return 7;
        const int fd = open(entry.path().c_str(), O_WRONLY | O_CLOEXEC);
        if (fd >= 0) { close(fd); return 7; }
        if (errno != EROFS) return 7;
    }
    if (op == "decode" && files == 1) {
        std::cerr << "control: frame-only read-only decode\n";
        return bmk_smoke_normal_main(argc, argv);
    }
    if (op != "encode" || files != 2 || argc != 9) return 7;
    std::cerr << "control: original-only read-only encode\n";
    const auto bytes = fs::file_size(argv[6]);
    if (plugin == "raw-store" && bytes == 0) {
        std::cerr << "control: worker error\n";
        return 3;
    }
    if (plugin == "zstd" && bytes == 0) {
        std::cerr << "control: actual SIGSEGV\n";
        raise(SIGSEGV);
    }
    if (plugin == "alp-auto" && bytes == 0) {
        std::cerr << "control: timeout wait\n";
        sleep(30);
    }
    if (plugin == "alp-auto" && bytes == 65536) {
        std::cerr << "control: cancellation wait\n";
        sleep(30);
    }
    return bmk_smoke_normal_main(argc, argv);
}
