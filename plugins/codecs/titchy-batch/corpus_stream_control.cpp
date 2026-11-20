// M3: one native Titchy packet session per complete V column.
#include "titchy.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
using Bytes = std::vector<uint8_t>;
using Clock = std::chrono::steady_clock;
constexpr size_t rows_cap=1000000, chunk=4, target=7, split=1000, packet_cap=1024;
constexpr size_t wire_cap=21+((rows_cap+chunk-1)/chunk)*(6+packet_cap);
constexpr titchy_config cfg{64,chunk,split,0,0.25,72};
void check(bool ok,const char* msg) { if (!ok) throw std::runtime_error(msg); }
uint64_t ns(Clock::time_point start) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
}
void put(Bytes& out,uint64_t v,size_t n) { for(size_t i=0;i<n;++i) out.push_back(uint8_t(v>>(8*i))); }
uint64_t get(const Bytes& in,size_t pos,size_t n) {
    check(pos<=in.size() && n<=in.size()-pos && n<=8,"invalid wire extent");
    uint64_t v=0;
    for(size_t i=0;i<n;++i) v|=uint64_t(in[pos+i])<<(8*i);
    return v;
}
Bytes read(const char* path,size_t cap) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    const auto n=f.tellg();
    check(n>0 && uint64_t(n)<=cap,"input exceeds declared bound or is empty");
    Bytes b(static_cast<size_t>(n));
    f.seekg(0);
    check(bool(f.read(reinterpret_cast<char*>(b.data()),n)),"read failed");
    return b;
}
void write(const char* path,const Bytes& b) {
    std::ofstream f(path,std::ios::binary|std::ios::trunc);
    f.write(reinterpret_cast<const char*>(b.data()),b.size()); f.close();
    check(bool(f),"write failed");
}
Bytes policy_wire() {
    Bytes b{'T','S','C','1',64,chunk};
    put(b,split,2); put(b,0,2); put(b,target,2);
    uint64_t bits; static_assert(sizeof(bits)==sizeof(cfg.threshold));
    std::memcpy(&bits,&cfg.threshold,8); put(b,bits,8);
    put(b,cfg.max_active_bytes,8); put(b,0,4); return b;
}
using Enc=std::unique_ptr<titchy_stream_encoder,decltype(&titchy_stream_encoder_free)>;
using Dec=std::unique_ptr<titchy_stream_decoder,decltype(&titchy_stream_decoder_free)>;
auto stats(titchy_stream_encoder* e) {
    titchy_stream_stats s{}; titchy_config actual{}; size_t goal=0;
    check(!titchy_stream_encoder_info(e,&actual,&goal,&s) && goal==target &&
          actual.bits_per_sample==64 && actual.samples_per_chunk==chunk && actual.chunks_per_split==split &&
          actual.endian==0 && actual.threshold==cfg.threshold && actual.max_active_bytes==cfg.max_active_bytes,"native stream configuration drift");
    return s;
}
struct Trace {
    size_t packets=0, chunks=0, payload=0, first_push=0, emitted_on_finish=0, capacity_checks=0;
    uint64_t first_ns=0, wall_ns=0;
};
Bytes encode(titchy_stream_encoder* enc,const Bytes& input,Trace& t,bool controls) {
    const size_t n=input.size()/8;
    Bytes archive{'T','S','T','R',1,64,chunk}; put(archive,split,2); put(archive,n,8); put(archive,0,4);
    std::array<uint8_t,packet_cap> packet{};
    const auto start=Clock::now();
    auto drain=[&](size_t pushed,bool finish) {
        for (;;) {
            size_t bytes=0, chunks=0;
            check(!titchy_stream_pop(enc,packet.data(),packet.size(),&bytes,&chunks),"native pop failed");
            if (!chunks) { check(!bytes,"empty pop produced bytes"); break; }
            check(bytes && bytes<=packet.size() && chunks<=target &&
                  t.chunks+chunks<=(n+chunk-1)/chunk,"invalid native packet extent");
            if (!t.packets) { t.first_push=pushed; t.first_ns=ns(start); }
            ++t.packets; t.chunks+=chunks; t.payload+=bytes; t.emitted_on_finish+=finish;
            put(archive,chunks,2); put(archive,bytes,4); archive.insert(archive.end(),packet.begin(),packet.begin()+bytes);
        }
    };
    for (size_t i=0;i<n;++i) {
        const auto v=get(input,i*8,8);
        check(!titchy_stream_push(enc,v),"native push failed");
        if (controls && !t.packets && stats(enc).ready_packets) {
            const auto st=stats(enc);
            size_t b=99,c=99;
            check(titchy_stream_push(enc,v)==TITCHY_CAPACITY && titchy_stream_finish(enc)==TITCHY_CAPACITY &&
                  titchy_stream_pop(enc,nullptr,0,&b,&c)==TITCHY_CAPACITY && !b && !c,"native backpressure control failed");
            const auto after=stats(enc);
            check(st.samples==after.samples && st.ready_packets==after.ready_packets,"rejected push changed pending state");
            t.capacity_checks=3;
        }
        drain(i+1,false);
    }
    check(!titchy_stream_finish(enc),"native finish failed");
    drain(n,true);
    t.wall_ns=ns(start);
    auto end=stats(enc);
    check(t.packets && t.chunks==(n+chunk-1)/chunk && end.finished && end.samples==n && !end.ready_packets &&
          end.active_bases<=2 && archive.size()<=wire_cap,"stream extent or terminal state differs");
    check(titchy_stream_push(enc,0)==TITCHY_INVALID && titchy_stream_finish(enc)==TITCHY_INVALID,"finished boundary accepted");
    for (size_t i=0;i<4;++i) archive[17+i]=uint8_t(t.packets>>(8*i));
    return archive;
}
void encode_files(const char* input,const char* archive,const char* conf) {
    const auto raw=read(input,rows_cap*8);
    check(raw.size()%8==0,"input is not u64 aligned");
    titchy_stream_encoder* e=nullptr;
    check(!titchy_stream_encoder_create(&cfg,target,raw.size()/8,&e) && e,"native encoder create");
    Enc enc(e,titchy_stream_encoder_free);
    // Primary latency is not inflated by negative-call/reset checks.
    Trace t,probe;
    const auto wire=encode(enc.get(),raw,t,false);
    check(!titchy_stream_encoder_reset(enc.get()) && !stats(enc.get()).samples,"native encoder reset");
    check(encode(enc.get(),raw,probe,true)==wire && probe.first_push==t.first_push &&
          probe.emitted_on_finish==t.emitted_on_finish,"reset replay differs");
    write(archive,wire); write(conf,policy_wire());
    std::cout<<"{\"logical_samples\":"<<raw.size()/8<<",\"packets\":"<<t.packets<<",\"chunks\":"<<t.chunks
        <<",\"payload_bytes\":"<<t.payload<<",\"first_packet_after_push\":"<<t.first_push
        <<",\"first_packet_ns\":"<<t.first_ns<<",\"packets_emitted_on_finish\":"<<t.emitted_on_finish
        <<",\"wall_ns\":"<<t.wall_ns<<",\"backpressure_replay_checks\":"<<probe.capacity_checks
        <<",\"reset_replay_bit_exact\":true}\n";
}
Bytes decode(titchy_stream_decoder* dec,const Bytes& wire,size_t n,size_t packets,bool verify_capacity) {
    const auto padded=((n+chunk-1)/chunk)*chunk;
    Bytes out; out.reserve(padded*8);
    std::array<uint64_t,target*chunk> values{};
    size_t pos=21;
    for (size_t i=0;i<packets;++i) {
        const size_t c=get(wire,pos,2), b=get(wire,pos+2,4); pos+=6;
        check(c>0 && c<=target && b>0 && b<=packet_cap && b<=wire.size()-pos && c*chunk*8<=padded*8-out.size(),"packet record bounds");
        size_t got=99;
        if (verify_capacity && !i) {
            check(titchy_stream_decode_packet(dec,wire.data()+pos,b,c,values.data(),0,&got)==TITCHY_CAPACITY && !got,
                  "native packet capacity control failed");
        }
        check(!titchy_stream_decode_packet(dec,wire.data()+pos,b,c,values.data(),values.size(),&got) && got==c*chunk,"native packet rejected");
        for(size_t j=0;j<got;++j) put(out,values[j],8);
        pos+=b;
    }
    check(pos==wire.size() && out.size()==padded*8,"archive was not fully consumed");
    check(std::all_of(out.begin()+n*8,out.end(),[](uint8_t x){return x==0;}),"nonzero padded tail");
    out.resize(n*8); return out;
}
void decode_files(const char* archive,const char* conf,const char* output) {
    const auto wire=read(archive,wire_cap);
    check(read(conf,32)==policy_wire() && wire.size()>=21 && !std::memcmp(wire.data(),"TSTR\1",5) &&
          get(wire,5,1)==64 && get(wire,6,1)==chunk && get(wire,7,2)==split,"unknown stream format or config");
    const auto n=get(wire,9,8), packets=get(wire,17,4);
    check(n>0 && n<=rows_cap && packets>0 && packets<=(n+chunk-1)/chunk,"stream extent outside quota");
    const size_t padded=((n+chunk-1)/chunk)*chunk;
    titchy_stream_decoder* d=nullptr;
    check(!titchy_stream_decoder_create(&cfg,padded,&d) && d,"native decoder create");
    Dec dec(d,titchy_stream_decoder_free);
    const auto start=Clock::now();
    const auto restored=decode(dec.get(),wire,n,packets,false);
    const auto elapsed=ns(start);
    check(!titchy_stream_decoder_reset(dec.get()) && decode(dec.get(),wire,n,packets,true)==restored,"native decoder reset replay differs");
    write(output,restored);
    std::cout<<"{\"logical_samples\":"<<n<<",\"padding_samples\":"<<padded-n<<",\"packets\":"<<packets
        <<",\"wall_ns\":"<<elapsed<<",\"decoder_capacity_retry_verified\":true,\"reset_replay_bit_exact\":true}\n";
}
}
int main(int argc,char** argv) {
    try {
        check(argc==5,"expected encode INPUT ARCHIVE CONFIG or decode ARCHIVE CONFIG OUTPUT");
        const std::string_view op(argv[1]);
        if(op=="encode") encode_files(argv[2],argv[3],argv[4]);
        else if(op=="decode") decode_files(argv[2],argv[3],argv[4]);
        else check(false,"unknown stream command");
        return std::cout.good()?0:2;
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
