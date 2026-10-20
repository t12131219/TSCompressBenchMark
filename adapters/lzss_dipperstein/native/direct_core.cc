#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "../../../native/include/tsbench_core_bytes.hpp"
#include <cerrno>
#include <climits>
#include <cstdio>
extern "C" {
#include "lzss.h"
}

namespace {
using namespace tsbench_bytes;
struct DippersteinCore : Context {
    DippersteinCore(const tsbench_core_config& config,bool decoder):Context(config,decoder) {
        if(bytes>UINT32_MAX)throw Unsupported("Dipperstein LZSS exceeds its registered uint32 work limit");
        if(!decoder) {
            Parameters p(config.parameters_json);
            require(p.integer("offset_bits")==12 && p.integer("length_bits")==4 && p.integer("initial_byte")==32 &&
                    p.string("match_finder")=="BINARY_TREE","unsupported Dipperstein fixed dictionary configuration");
        }
    }
};
struct Destination { uint8_t* data;size_t size=0,capacity;bool full=false; };
ssize_t write_memory(void* cookie,const char* data,size_t size) {
    auto& output=*static_cast<Destination*>(cookie);
    if(size>output.capacity-output.size) {output.full=true;errno=ENOSPC;return -1;}
    if(size)std::memcpy(output.data+output.size,data,size);
    output.size+=size;
    return static_cast<ssize_t>(size);
}
size_t file_codec(bool encoding,const uint8_t* input,size_t size,uint8_t* output,size_t capacity) {
    // Native API is FILE*-based. Cookie streams write directly to caller
    // storage, avoiding the legacy open_memstream + whole-output memcpy.
    Destination destination{output,0,capacity,false};cookie_io_functions_t functions{};functions.write=write_memory;
    auto source_file=std::unique_ptr<FILE,decltype(&fclose)>(fmemopen(const_cast<uint8_t*>(source(input)),size,"rb"),fclose);
    auto output_file=std::unique_ptr<FILE,decltype(&fclose)>(fopencookie(&destination,"wb",functions),fclose);
    require(bool(source_file) && bool(output_file),"Dipperstein memory stream creation failed");
    int status=encoding?EncodeLZSS(source_file.get(),output_file.get()):DecodeLZSS(source_file.get(),output_file.get());
    int flushed=fflush(output_file.get());bool input_error=ferror(source_file.get())!=0,output_error=ferror(output_file.get())!=0;
    int source_closed=fclose(source_file.release()),output_closed=fclose(output_file.release());
    if(destination.full)throw Capacity("Dipperstein native output exceeds destination");
    require(status==0 && flushed==0 && !input_error && !output_error && source_closed==0 && output_closed==0,
            "Dipperstein native FILE codec failed");
    return destination.size;
}
size_t dipperstein_bound(size_t n) {return add(8,add(n,add(n,7)/8));}
}
TSBENCH_BYTE_COMMON_API(DippersteinCore)
extern "C" uint32_t tsbench_core_storage(void) { return 3; }
extern "C" int tsbench_core_bound(void* raw,const uint8_t*,size_t n,size_t* bound) {
    auto c=static_cast<DippersteinCore*>(raw);return guard(c,[&]{encoding(c,n);require(bound,"null Dipperstein bound");*bound=dipperstein_bound(n);});
}
extern "C" int tsbench_core_encode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<DippersteinCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);encoding(c,n);
        if(cap<dipperstein_bound(n))throw Capacity("Dipperstein destination below literal worst-case bound");
        put64(out,n);size_t used=n?file_codec(true,in,n,out+8,cap-8):0;
        caller_result(out,add(8,used),cap,result);
    });
}
extern "C" int tsbench_core_decode(void* raw,const uint8_t* in,size_t n,uint8_t* out,size_t cap,tsbench_core_result* result) {
    auto c=static_cast<DippersteinCore*>(raw);return guard(c,[&]{
        arguments(c,in,n,out,cap,result);decoding(c,cap);
        require(n>=8 && get64(in)==c->bytes,"Dipperstein complete-stream length differs from task");
        require(n-8<=add(c->bytes,add(c->bytes,7)/8),"Dipperstein encoded payload exceeds literal bound");
        if(c->bytes==0)require(n==8,"Dipperstein empty stream has trailing tokens");
        else require(file_codec(false,in+8,n-8,out,c->bytes)==c->bytes,"Dipperstein decoded length differs from complete stream");
        caller_result(out,c->bytes,cap,result);
    });
}
