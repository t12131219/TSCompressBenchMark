// Bounded, same-ABI result-ready frame batches; no I/O inside timing extents.
#include "plugin_loader.hpp"

#include <charconv>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sched.h>
#include <string>
#include <vector>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
static_assert(Clock::is_steady);
constexpr size_t value_limit = 32*1024*1024, schema_limit = 65536, max_budget = 128*1024*1024;

void require(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
size_t number(std::string_view text, size_t lo, size_t hi) {
    size_t v{};
    auto rc=std::from_chars(text.data(),text.data()+text.size(),v);
    require(rc.ec==std::errc{} && rc.ptr==text.data()+text.size() && v>=lo && v<=hi,"invalid numeric batch argument");
    return v;
}
std::vector<uint8_t> read(const char *name, size_t limit) {
    require(std::filesystem::is_regular_file(name),"batch input is not a regular file");
    std::ifstream file(name,std::ios::binary|std::ios::ate);
    const auto size=file.tellg();
    require(size>=0 && static_cast<uint64_t>(size)<=limit,"batch input exceeds cap");
    std::vector<uint8_t> out(static_cast<size_t>(size));
    file.seekg(0);
    require((!size || bool(file.read(reinterpret_cast<char *>(out.data()),size))) && file.peek()==EOF && !file.bad(),
            "batch input changed or could not be read");
    return out;
}
bool equal(const void *a,const void *b,size_t n) {return !n || (a && b && std::memcmp(a,b,n)==0);}
int64_t elapsed(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count();
}
std::string info(tsbench::Context &ctx) {
    const auto out=ctx.execution_info();
    const auto &v=out->get();
    require(v.size && v.size<=schema_limit,"invalid warmup execution info");
    return {reinterpret_cast<const char *>(v.data),static_cast<size_t>(v.size)};
}
void verify(const bmk_object_view &v, const bmk_array_view &input,
            const std::vector<uint8_t> &src,const std::vector<uint8_t> &schema) {
    require(v.column_count==1 && v.columns && v.schema_bytes==schema.size() &&
            equal(v.schema_json,schema.data(),schema.size()),"decoded schema differs from input");
    const auto &c=v.columns[0];
    require(c.struct_size>=sizeof(c) && c.dtype==input.dtype && c.rank==1 && !c.flags && !c.validity &&
            !c.validity_bytes && !c.validity_bit_offset && c.shape[0]==input.shape[0] &&
            c.strides_bytes[0]==input.strides_bytes[0] && c.origin_offset<=c.storage_bytes &&
            src.size()<=c.storage_bytes-c.origin_offset && c.origin_offset<=SIZE_MAX-src.size() &&
            (src.empty() || (c.storage && equal(static_cast<const uint8_t *>(c.storage)+c.origin_offset,src.data(),src.size()))),
            "decoded result does not match every original bit");
}
}

int main(int argc,char **argv) {
    try {
        require(argc==13,"expected LIB ID OPTIONS steady|cold DTYPE LOOPS WARMUPS BUDGET VALUES SCHEMA REFERENCE KIND");
        const std::string_view lifecycle=argv[4], options=argv[3];
        require((lifecycle=="steady" || lifecycle=="cold") && options.size()<=schema_limit,"unknown batch lifecycle/options");
        const bool steady=lifecycle=="steady";
        const uint32_t dtype=number(argv[5],2,10);
        require(dtype==BMK_U8 || dtype==BMK_F64,"unsupported batch probe type");
        const size_t width=dtype==BMK_U8?1:8, loops=number(argv[6],1,512), warmups=number(argv[7],1,8),
                     budget=number(argv[8],1,max_budget);
        const auto src=read(argv[9],value_limit), schema=read(argv[10],schema_limit);
        const size_t logical=src.size()+schema.size();
        require(src.size()%width==0 && logical<=budget/loops,"invalid source shape or predicted retention budget");
#ifdef TSBENCH_BATCH_LINKED
        const auto module=tsbench::PluginModule::from_linked(argv[1],argv[2],&bmk_get_plugin);
        constexpr std::string_view lane="linked_entry";
#else
        const auto module=tsbench::PluginModule::load(argv[1],argv[2]);
        constexpr std::string_view lane="dlopen";
#endif
        require(std::string_view(argv[12])==lane,"unexpected executable for lane");
        bmk_array_view col{};
        col.struct_size=sizeof(col); col.dtype=dtype; col.rank=1; col.storage=src.data(); col.storage_bytes=src.size();
        col.shape[0]=src.size()/width; col.strides_bytes[0]=width;
        const bmk_object_view input{sizeof(input),1,&col,schema.data(),schema.size()};
        std::unique_ptr<tsbench::Context> encoder,decoder;
        if (steady) {
            encoder=std::make_unique<tsbench::Context>(module,options);
            decoder=std::make_unique<tsbench::Context>(module,options);
        }
        auto encode=[&](std::string *metadata=nullptr) {
            if (steady) {
                encoder->reset(0);
                auto result=encoder->encode(input);
                if (metadata) *metadata=info(*encoder);
                return result;
            }
            tsbench::Context ctx(module,options);
            auto result=ctx.encode(input);
            if (metadata) *metadata=info(ctx);
            return result;  // context destroyed before the cold operation returns
        };
        auto decode=[&](const bmk_blob &frame,std::string *metadata=nullptr) {
            if (steady) {
                decoder->reset(0);
                auto result=decoder->decode(frame.data,frame.size);
                if (metadata) *metadata=info(*decoder);
                return result;
            }
            tsbench::Context ctx(module,options);
            auto result=ctx.decode(frame.data,frame.size);
            if (metadata) *metadata=info(ctx);
            return result;
        };
        std::string enc_info, dec_info;
        std::vector<uint8_t> reference;
        for (size_t i=0;i<warmups;++i) {
            const auto frame=encode(&enc_info);
            const auto &f=frame->get();
            require(f.size && f.capacity<=budget-logical,"single warmup frame exceeds retention budget");
            const auto restored=decode(f,&dec_info);
            verify(restored->get(),col,src,schema);
            if (i==0) reference.assign(f.data,f.data+f.size);
            else require(f.size==reference.size() && equal(f.data,reference.data(),reference.size()),"warmup output changed");
        }
        require(reference.size()<=budget-loops*logical,"reference does not fit batch retention budget");
        const size_t cap_budget=budget-loops*logical-reference.size();
        std::vector<std::unique_ptr<tsbench::Blob>> frames(loops);
        std::vector<std::unique_ptr<tsbench::Object>> values(loops);
        size_t capacity=0;
        const int enc_cpu_before=sched_getcpu();
        const auto enc_start=Clock::now();
        for (auto &slot:frames) {
            slot=encode();
            const size_t cap=slot->get().capacity;
            require(cap<=cap_budget-capacity,"retained frame capacity exceeds budget");
            capacity+=cap;
        }
        const auto enc_end=Clock::now();
        const int enc_cpu_after=sched_getcpu();
        for (const auto &slot:frames) {
            const auto &f=slot->get();
            require(f.size==reference.size() && equal(f.data,reference.data(),reference.size()),"retained encoded frame differs");
        }
        const int dec_cpu_before=sched_getcpu();
        const auto dec_start=Clock::now();
        for (size_t i=0;i<loops;++i) values[i]=decode(frames[i]->get());
        const auto dec_end=Clock::now();
        const int dec_cpu_after=sched_getcpu();
        for (const auto &slot:values) verify(slot->get(),col,src,schema);
        const auto release_start=Clock::now();
        values.clear(); frames.clear();
        const auto release_end=Clock::now();
        // This file is an untimed warmup/reference sample, not one of the timed results.
        std::ofstream out(argv[11],std::ios::binary|std::ios::trunc);
        out.write(reinterpret_cast<const char *>(reference.data()),static_cast<std::streamsize>(reference.size()));
        out.close();
        require(bool(out),"cannot publish batch byte reference");
        std::cout<<"{\"lane\":\""<<lane<<"\",\"lifecycle\":\""<<lifecycle<<"\",\"pid\":"<<::getpid()
                 <<",\"loops\":"<<loops<<",\"warmups\":"<<warmups<<",\"encoded_verified\":"<<loops
                 <<",\"decoded_verified\":"<<loops<<",\"encode_batch_ns\":"<<elapsed(enc_start,enc_end)
                 <<",\"decode_batch_ns\":"<<elapsed(dec_start,dec_end)<<",\"release_ns\":"<<elapsed(release_start,release_end)
                 <<",\"frame_bytes_each\":"<<reference.size()<<",\"frame_capacity_total\":"<<capacity
                 <<",\"decoded_logical_and_schema_total\":"<<logical*loops<<",\"budget_bytes\":"<<budget
                 <<",\"encode_cpu_endpoints\":["<<enc_cpu_before<<','<<enc_cpu_after<<']'
                 <<",\"decode_cpu_endpoints\":["<<dec_cpu_before<<','<<dec_cpu_after<<']'
                 <<",\"warmup_encode_info\":"<<enc_info<<",\"warmup_decode_info\":"<<dec_info<<"}\n";
        return std::cout?0:1;
    } catch(const std::exception &error) {
        std::cerr<<"batch probe failed: "<<error.what()<<'\n';
        return 1;
    }
}
