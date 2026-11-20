// Instrumented snapshot of corpus_worker_control.cpp. Keep the sealed control unchanged.
#include "clock.hpp"
#include <optional>
#include "lzbench_extended.hpp"
#include "lzma.h"

#include <algorithm>
#include <charconv>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>

namespace {
using namespace lzbench_native;
using lzbench_clock::Trial;
constexpr size_t block_size = 131072, job_size = 524288, inner_span = 16384;
constexpr size_t memory_limit = 134217728, preset = 1;
constexpr auto check_type = LZMA_CHECK_CRC64;
constexpr size_t encode_in = 262139, encode_out = 65521, decode_in = 1 << 20, decode_out = 131071;

void check(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
size_t number(std::string_view s) {
    size_t value{};
    const auto r=std::from_chars(s.data(),s.data()+s.size(),value);
    check(r.ec==std::errc{} && r.ptr==s.data()+s.size(),"invalid native worker number");
    return value;
}
size_t size_of(std::ifstream& input) {
    const auto size = input.tellg();
    check(input && size>0,"invalid input extent");
    input.seekg(0);
    return static_cast<size_t>(size);
}
void report(Trial& t, std::string_view entry,size_t read,size_t written,const std::map<std::string,int64_t>& effective,
            size_t calls,size_t blocks=0,size_t fallback=0) {
    const auto j=get_worker_stats();
    t.functional << "{\"entry\":\"" << entry << "\",\"input_bytes\":" << read << ",\"output_bytes\":" << written
              << ",\"jobs\":{\"jobs\":" << j.jobs << ",\"worker_threads\":" << j.worker_threads
              << ",\"caller_jobs\":" << j.caller_jobs << "},\"calls\":" << calls
              << ",\"blocks\":" << blocks << ",\"uncompressed_fallback_blocks\":" << fallback << ",\"effective_parameters\":{";
    bool comma=false;
    for (const auto& [k,v]:effective) {
        if (comma) t.functional << ',';
        t.functional << '"' << k << "\":" << v;
        comma=true;
    }
    t.functional << "}}";
}

template<class Step>
void transfer(Trial& t, std::string_view entry,const char* source,const char* dest,size_t bound,bool encode,Step step,
              const std::map<std::string,int64_t>& effective) {
    std::ifstream input(source,std::ios::binary|std::ios::ate);
    const size_t size=size_of(input);
    std::ofstream out(dest,std::ios::binary);
    check(bool(out),"cannot open native output");
    bytes in(encode?encode_in:decode_in), output(encode?encode_out:decode_out);
    size_t loaded=0, offset=0, available=0, consumed=0, made=0, idle=0, calls=0;
    while (true) {
        if (offset==available && loaded<size) {
            available=std::min(in.size(),size-loaded); offset=0;
            check(bool(input.read(reinterpret_cast<char*>(in.data()),available)),"incomplete input span");
            loaded+=available;
        }
        const bool finish=loaded==size;
        const auto p=step(in.data()+offset,available-offset,output.data(),output.size(),finish);
        ++calls;
        check(p.consumed<=available-offset && p.produced<=output.size() && p.produced<=bound-made,"native span or output budget exceeded");
        offset+=p.consumed; consumed+=p.consumed; made+=p.produced;
        if (p.produced) {
            t.output(p.produced);
            check(bool(out.write(reinterpret_cast<const char*>(output.data()),p.produced)),"cannot write output span");
        }
        if (p.finished) {
            check(consumed==size && input.peek()==EOF && !input.bad(),"native final marker left trailing input");
            break;
        }
        idle=(p.consumed||p.produced)?0:idle+1;
        check(idle<16384,"native worker operation stalled");
    }
    out.close();
    check(out && made && (encode||made==bound),"native output extent differs");
    report(t,entry,consumed,made,effective,calls);
}

bool caller_block(Trial& t, lzma_block& block,const uint8_t* data,size_t size,bytes& out,size_t& written) {
    const auto bound=out.size();
    block.compressed_size=bound; block.uncompressed_size=block_size;
    check(t.framing.measure([&]{ return lzma_block_header_size(&block); })==LZMA_OK && block.header_size<bound,"invalid caller Block header reservation");
    lzma_stream stream=LZMA_STREAM_INIT;
    const auto end=[&t](lzma_stream* s){ t.cleanup.measure([&]{ lzma_end(s); }); };
    const std::unique_ptr<lzma_stream,decltype(end)> cleanup(&stream,end);
    check(t.setup.measure([&]{ return lzma_block_encoder(&stream,&block); })==LZMA_OK,"cannot initialize caller Block encoder");
    stream.next_in=data; stream.next_out=out.data()+block.header_size;
    stream.avail_out=bound-block.header_size;
    size_t offered=0;
    lzma_ret rc;
    do {
        if (!stream.avail_in && offered<size) {
            stream.avail_in=std::min(inner_span,size-offered); offered+=stream.avail_in;
        }
        rc=t.process.measure([&]{ return lzma_code(&stream,offered==size?LZMA_FINISH:LZMA_RUN); });
    } while (rc==LZMA_OK && stream.avail_out);
    if (rc==LZMA_STREAM_END) {
        check(stream.total_in==size && t.framing.measure([&]{ return lzma_block_header_encode(&block,out.data()); })==LZMA_OK,"caller Block boundary differs");
        written=block.header_size+stream.total_out;
        return false;
    }
    check(rc==LZMA_OK||rc==LZMA_BUF_ERROR,"caller Block compression failed");
    written=0;
    check(t.process.measure([&]{ return lzma_block_uncomp_encode(&block,data,size,out.data(),&written,bound); })==LZMA_OK,"cannot encode native fallback Block");
    return true;
}

void synchronous_encode(Trial& t, const char* source,const char* dest,size_t budget) {
    std::ifstream input(source,std::ios::binary|std::ios::ate);
    const auto size=size_of(input);
    std::ofstream out(dest,std::ios::binary);
    check(bool(out),"cannot open caller output");
    size_t written=0;
    const auto emit=[&](const uint8_t* ptr,size_t n){
        t.output(n);
        check(n<=budget-written && bool(out.write(reinterpret_cast<const char*>(ptr),n)),"caller output budget/write failed");
        written+=n;
    };
    lzma_options_lzma opt{};
    check(!t.setup.measure([&]{ return lzma_lzma_preset(&opt,preset); }),"invalid caller preset");
    lzma_filter filters[]={{LZMA_FILTER_LZMA2,&opt},{LZMA_VLI_UNKNOWN,nullptr}};
    const auto memory=t.setup.measure([&]{ return lzma_raw_encoder_memusage(filters); });
    check(memory!=UINT64_MAX && memory<=memory_limit,"caller encoder memory limit");
    lzma_stream_flags flags{};
    flags.check=check_type;
    uint8_t header[LZMA_STREAM_HEADER_SIZE];
    check(t.framing.measure([&]{ return lzma_stream_header_encode(&flags,header); })==LZMA_OK,"caller stream header failed");
    emit(header,sizeof(header));
    const auto release=[&t](lzma_index* i){ t.cleanup.measure([&]{ lzma_index_end(i,nullptr); }); };
    const std::unique_ptr<lzma_index,decltype(release)> index(t.framing.measure([&]{ return lzma_index_init(nullptr); }),release);
    check(bool(index),"cannot allocate caller Index");
    bytes source_block(block_size), scratch(t.framing.measure([&]{ return lzma_block_buffer_bound(block_size); }));
    size_t at=0, blocks=0, fallback=0;
    for (;at<size;) {
        auto n=std::min(block_size,size-at);
        check(bool(input.read(reinterpret_cast<char*>(source_block.data()),n)),"short caller block");
        lzma_block block{}; block.check=flags.check; block.filters=filters;
        size_t made=0;
        fallback+=caller_block(t,block,source_block.data(),n,scratch,made);
        const auto unpadded=t.framing.measure([&]{ return lzma_block_unpadded_size(&block); });
        check(block.uncompressed_size==n && t.framing.measure([&]{ return lzma_index_append(index.get(),nullptr,unpadded,n); })==LZMA_OK,
              "cannot append caller Index record");
        emit(scratch.data(),made); at+=n; ++blocks;
    }
    check(input.peek()==EOF && !input.bad(),"trailing caller input");
    flags.backward_size=t.framing.measure([&]{ return lzma_index_size(index.get()); });
    check(flags.backward_size<=budget-written,"caller Index exceeds output budget");
    bytes tail(flags.backward_size);
    size_t pos=0;
    check(t.framing.measure([&]{ return lzma_index_buffer_encode(index.get(),tail.data(),&pos,tail.size()); })==LZMA_OK && pos==tail.size(),"cannot encode caller Index");
    emit(tail.data(),pos);
    check(t.framing.measure([&]{ return lzma_stream_footer_encode(&flags,header); })==LZMA_OK,"caller footer failed");
    emit(header,sizeof(header));
    out.close(); check(bool(out),"cannot finish caller output");
    report(t,"lzma_block_encoder",at,written,{{"block_size",block_size},{"preset",preset},{"check",check_type},
           {"memory_limit",memory_limit},{"dict_size",opt.dict_size},{"filter_id",LZMA_FILTER_LZMA2},
           {"raw_encoder_memory_bytes",static_cast<int64_t>(memory)},{"inner_input_span_bytes",inner_span}},blocks,blocks,fallback);
}

void run(Trial& t, std::string_view codec,std::string_view dir,std::string_view lane,const char* source,const char* dest,size_t budget) {
    const bool encode=dir=="encode";
    check((encode||dir=="decode") && (codec=="zstd"||codec=="xz") && budget,"invalid worker operation");
    reset_worker_stats();
    if (lane=="synchronous") {
        check(codec=="xz","synchronous comparator is XZ only");
        if (encode) return synchronous_encode(t,source,dest,budget);
        lzma_stream stream=LZMA_STREAM_INIT;
        const auto end=[&t](lzma_stream* s){ t.cleanup.measure([&]{ lzma_end(s); }); };
        const std::unique_ptr<lzma_stream,decltype(end)> cleanup(&stream,end);
        check(t.setup.measure([&]{ return lzma_stream_decoder(&stream,memory_limit,0); })==LZMA_OK,"caller XZ decode init");
        const auto step=[&](const uint8_t* in,size_t size,uint8_t* out,size_t cap,bool finish){
            stream.next_in=in; stream.avail_in=size; stream.next_out=out; stream.avail_out=cap;
            const auto rc=t.process.measure([&]{ return lzma_code(&stream,finish?LZMA_FINISH:LZMA_RUN); });
            check(rc==LZMA_OK||rc==LZMA_STREAM_END,"caller XZ decode failed");
            return progress{size-stream.avail_in, cap-stream.avail_out, rc==LZMA_STREAM_END};
        };
        return transfer(t,"lzma_stream_decoder",source,dest,budget,false,step,{{"memory_limit",memory_limit}});
    }
    const auto count=number(lane);
    configuration c;
    if (codec=="zstd") {
        check((encode && (count==0||count==2)) || (!encode && count==0),"invalid Zstd native worker lane");
        c.codec=LN_ZSTD; c.level=3;
        c.parameters={{"workers",count},{"job_size",job_size},{"checksum",0}};
    } else {
        check(count==1||count==2,"invalid XZ native worker lane");
        c.codec=LN_XZ; c.level=preset;
        c.parameters={{"block_size",block_size},{"check",check_type},{"memory_limit",memory_limit},{"threads",count}};
    }
    std::optional<session> state;
    t.setup.measure([&]{ state.emplace(c); });
    auto& s = *state;
    check(s.streaming(),"native byte session required");
    t.setup.measure([&]{ s.reset(encode); });
    const auto step=[&](const uint8_t* in,size_t size,uint8_t* out,size_t cap,bool finish){return t.process.measure([&]{ return s.process(encode,in,size,out,cap,finish); });};
    transfer(t,"lzbench_native::session::process",source,dest,budget,encode,step,s.effective_parameters());
    t.cleanup.measure([&]{ state.reset(); });
}
}

int main(int argc,char** argv) {
    try {
        check(argc==7,"usage: control {zstd|xz} {encode|decode} lane source dest output-cap");
        Trial trial;
        trial.start = lzbench_clock::Clock::now();
        run(trial,argv[1],argv[2],argv[3],argv[4],argv[5],number(argv[6]));
        trial.print();
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
