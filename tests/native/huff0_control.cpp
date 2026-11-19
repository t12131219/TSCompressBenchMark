#include "entropy_port.hpp"
extern "C" {
#define HUF_STATIC_LINKING_ONLY
#include "huf.h"
}
#include <dlfcn.h>

#include <array>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>

namespace ep = entropy_port;
namespace {
// Only this direct diagnostic executable interposes. The worker and library
// used for normal execution are not instrumented or forced to another ISA.
std::array<std::array<size_t,2>,3> decode_calls{};
std::array<size_t,2> table_encode_calls{};

template<class Fn> Fn next(const char *name) {
    auto fn = reinterpret_cast<Fn>(dlsym(RTLD_NEXT,name));
    if (!fn) std::abort();
    return fn;
}
size_t observe(size_t slot,int bmi2,size_t size,size_t result) {
    if ((bmi2 != 0 && bmi2 != 1) || (!TSBENCH_ENTROPY_DYNAMIC_BMI2 && bmi2)) std::abort();
    if (result == size) ++decode_calls[slot][bmi2];
    return result;
}
void verify(bool ok,const char *why) {
    if (!ok) throw std::runtime_error(why);
}
ep::Bytes read(const char *path,size_t limit) {
    std::ifstream f(path,std::ios::binary | std::ios::ate);
    const auto end = f.tellg();
    verify(end >= 0 && uint64_t(end) <= limit,"invalid diagnostic input path or length");
    ep::Bytes result(static_cast<size_t>(end));
    f.seekg(0);
    if (!result.empty()) verify(bool(f.read(reinterpret_cast<char *>(result.data()),result.size())),"read failed");
    return result;
}
void write(const char *path,const ep::Bytes &bytes) {
    std::ofstream f(path,std::ios::binary | std::ios::trunc);
    verify(bool(f),"open output failed");
    if (!bytes.empty()) f.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());
    f.close();
    verify(bool(f),"write output failed");
}
void metadata(size_t streams,size_t log) {
    std::cout << "{\"dynamic_bmi2_compiled\":" << (TSBENCH_ENTROPY_DYNAMIC_BMI2 ? "true" : "false")
              << ",\"cpu_bmi2_available\":" << (__builtin_cpu_supports("bmi2") ? "true" : "false")
              << ",\"cpu_backend\":\"" << ep::cpu_backend()
              << "\",\"implementation\":\"" << ep::implementation_id() << "\",\"streams\":" << streams
              << ",\"effective_table_log\":" << log << ",\"table_encode_calls\":["
              << table_encode_calls[0] << ',' << table_encode_calls[1] << "],\"completed_decode_calls\":[";
    for (size_t i=0;i<decode_calls.size();++i) {
        if (i) std::cout << ',';
        std::cout << '[' << decode_calls[i][0] << ',' << decode_calls[i][1] << ']';
    }
    std::cout << "]}\n";
}
}

extern "C" size_t HUF_decompress4X_hufOnly_wksp_bmi2(HUF_DTable *table,void *dst,size_t dst_size,
        const void *src,size_t src_size,void *work,size_t work_size,int bmi2) {
    static const auto fn = next<decltype(&HUF_decompress4X_hufOnly_wksp_bmi2)>("HUF_decompress4X_hufOnly_wksp_bmi2");
    return observe(0,bmi2,dst_size,fn(table,dst,dst_size,src,src_size,work,work_size,bmi2));
}
extern "C" size_t HUF_decompress1X_usingDTable_bmi2(void *dst,size_t dst_size,const void *src,
        size_t src_size,const HUF_DTable *table,int bmi2) {
    static const auto fn = next<decltype(&HUF_decompress1X_usingDTable_bmi2)>("HUF_decompress1X_usingDTable_bmi2");
    return observe(1,bmi2,dst_size,fn(dst,dst_size,src,src_size,table,bmi2));
}
extern "C" size_t HUF_decompress4X_usingDTable_bmi2(void *dst,size_t dst_size,const void *src,
        size_t src_size,const HUF_DTable *table,int bmi2) {
    static const auto fn = next<decltype(&HUF_decompress4X_usingDTable_bmi2)>("HUF_decompress4X_usingDTable_bmi2");
    return observe(2,bmi2,dst_size,fn(dst,dst_size,src,src_size,table,bmi2));
}
extern "C" size_t HUF_compress1X_usingCTable(void *dst,size_t dst_size,const void *src,size_t src_size,const HUF_CElt *table) {
    static const auto fn = next<decltype(&HUF_compress1X_usingCTable)>("HUF_compress1X_usingCTable");
    ++table_encode_calls[0];
    return fn(dst,dst_size,src,src_size,table);
}
extern "C" size_t HUF_compress4X_usingCTable(void *dst,size_t dst_size,const void *src,size_t src_size,const HUF_CElt *table) {
    static const auto fn = next<decltype(&HUF_compress4X_usingCTable)>("HUF_compress4X_usingCTable");
    ++table_encode_calls[1];
    return fn(dst,dst_size,src,src_size,table);
}

int main(int argc,char **argv) {
    try {
        verify(argc >= 4,"expected operation plus input and output");
        const std::string_view op = argv[1];
        if (op == "fec-encode" || op == "fec-decode") {
            verify(argc == 4,"expected FEC1 input/output");
            // Direct diagnostic deliberately caps inputs more tightly than the worker.
            const auto src = read(argv[2],8*ep::block_size);
            ep::Bytes out;
            ep::Codec codec(ep::Algorithm::Huff);
            if (op == "fec-encode") codec.encode(src,out,true);
            else codec.decode(src,out);
            write(argv[3],out);
            metadata(0,0);
        } else if (op == "train") {
            verify(argc == 5,"expected streams, training input, model output");
            const std::string_view streams = argv[2];
            verify(streams == "1" || streams == "4","unsupported Huff0 stream count");
            const ep::TableCodec codec(ep::Algorithm::Huff,read(argv[3],ep::block_size),0,streams == "1" ? 1 : 4);
            write(argv[4],codec.model());
            metadata(codec.huffman_streams(),codec.effective_table_log());
        } else {
            verify((op == "table-encode" || op == "table-decode") && (argc-3)%2 == 0,"invalid table operation");
            const auto model = read(argv[2],1024);
            verify(model.size() >= 8 && model[4] == unsigned(ep::Algorithm::Huff),"not a Huff0 model");
            const ep::TableCodec codec(model);
            for (int i=3;i<argc;i+=2) {
                const auto src = read(argv[i],ep::block_size+9);
                write(argv[i+1],op == "table-encode" ? codec.encode_block(src) : codec.decode_block(src));
            }
            metadata(codec.huffman_streams(),codec.effective_table_log());
        }
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
