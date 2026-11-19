// Bounded driver for the frozen C11 packet API, not a new codec or worker ABI.
#include "titchy.h"
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Bytes = std::vector<uint8_t>;
using Values = std::vector<uint64_t>;
constexpr size_t limit = 128 << 10, count = 4013, chunk = 4, target = 7, split = 1000;
constexpr size_t padded = 4016;
constexpr titchy_config policy{64, chunk, split, 0, 0.25, 72};
struct Packet { size_t chunks; Bytes wire; };
void check(bool condition) { if (!condition) throw std::runtime_error("Titchy packet contract differs"); }
void put(Bytes &out, uint64_t x, size_t n) {
    for (size_t i = 0; i < n; ++i) out.push_back(uint8_t(x >> (8*i)));
}
uint64_t get(const Bytes &in, size_t pos, size_t n) {
    check(pos <= in.size() && n <= in.size()-pos && n <= 8);
    uint64_t x = 0;
    for (size_t i = 0; i < n; ++i) x |= uint64_t(in[pos+i]) << (8*i);
    return x;
}
Bytes load(const char *path, size_t cap) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    auto n = f.tellg();
    check(n >= 0 && uint64_t(n) <= cap);
    Bytes b(static_cast<size_t>(n));
    f.seekg(0);
    check(bool(f.read(reinterpret_cast<char *>(b.data()), b.size())));
    return b;
}
void save(const char *path, const Bytes &b) {
    std::ofstream f(path, std::ios::binary);
    f.write(reinterpret_cast<const char *>(b.data()), b.size());
    f.close();
    check(bool(f));
}
Bytes config_wire() {
    Bytes wire{'T','S','C','1',64,chunk};
    put(wire,split,2); put(wire,0,2); put(wire,target,2);
    uint64_t bits;
    static_assert(sizeof(bits)==sizeof(policy.threshold));
    std::memcpy(&bits,&policy.threshold,8);
    put(wire,bits,8); put(wire,policy.max_active_bytes,8); put(wire,0,4);
    return wire;
}
using Encoder = std::unique_ptr<titchy_stream_encoder,decltype(&titchy_stream_encoder_free)>;
using Decoder = std::unique_ptr<titchy_stream_decoder,decltype(&titchy_stream_decoder_free)>;
Encoder encoder(size_t n) {
    titchy_stream_encoder *p = nullptr;
    check(titchy_stream_encoder_create(&policy,target,n,&p)==TITCHY_OK && p);
    return Encoder(p,titchy_stream_encoder_free);
}
Decoder decoder(const titchy_config &conf,size_t n) {
    titchy_stream_decoder *p = nullptr;
    check(titchy_stream_decoder_create(&conf,n,&p)==TITCHY_OK && p);
    return Decoder(p,titchy_stream_decoder_free);
}
auto stats(titchy_stream_encoder *enc) {
    titchy_stream_stats s{};
    size_t goal = 0;
    titchy_config actual{};
    check(titchy_stream_encoder_info(enc,&actual,&goal,&s)==TITCHY_OK && goal==target &&
          actual.bits_per_sample==policy.bits_per_sample && actual.samples_per_chunk==policy.samples_per_chunk &&
          actual.chunks_per_split==policy.chunks_per_split && actual.endian==policy.endian &&
          actual.threshold==policy.threshold && actual.max_active_bytes==policy.max_active_bytes);
    return s;
}
bool same(const titchy_stream_stats &a,const titchy_stream_stats &b) {
    return a.samples==b.samples && a.chunks==b.chunks && a.dictionary_bases==b.dictionary_bases &&
        a.active_bases==b.active_bases && a.pending_chunks==b.pending_chunks && a.ready_packets==b.ready_packets &&
        a.id_width==b.id_width && a.deviation_width==b.deviation_width && a.finished==b.finished;
}
Packet pop(titchy_stream_encoder *enc,size_t cap=limit,int expected=TITCHY_OK) {
    Bytes wire(cap);
    size_t bytes=99,chunks=99;
    check(titchy_stream_pop(enc,wire.data(),cap,&bytes,&chunks)==expected);
    check(bytes<=cap && chunks<=target && (!bytes)==(!chunks) && (expected==TITCHY_OK || !bytes));
    wire.resize(bytes);
    return {chunks,std::move(wire)};
}
struct Trace {
    std::vector<size_t> emissions;
    size_t active=0,ready=0;
    titchy_stream_stats end{};
    int blocked_push=0,blocked_finish=0,push_after_finish=0,finish_after_finish=0;
};
Bytes encode(titchy_stream_encoder *enc,const Bytes &input,Trace &t,bool negative) {
    Bytes wire{'T','S','T','R',1,64,chunk};
    put(wire,split,2); put(wire,count,8); put(wire,0,4);
    size_t packets=0;
    auto drain = [&]() {
        auto p=pop(enc);
        if (!p.chunks) return false;
        ++packets;
        put(wire,p.chunks,2); put(wire,p.wire.size(),4);
        check(wire.size()<=limit && p.wire.size()<=limit-wire.size());
        wire.insert(wire.end(),p.wire.begin(),p.wire.end());
        check(!pop(enc).chunks);
        return true;
    };
    check(!pop(enc).chunks);
    for (size_t i=0; i<count; ++i) {
        auto v=get(input,i*8,8);
        check(titchy_stream_push(enc,v)==TITCHY_OK);
        const auto s=stats(enc);
        t.active=std::max(t.active,s.active_bases); t.ready=std::max(t.ready,s.ready_packets);
        if (s.ready_packets && t.emissions.empty() && negative) {
            t.blocked_push=titchy_stream_push(enc,v);
            t.blocked_finish=titchy_stream_finish(enc);
            check(t.blocked_push==TITCHY_CAPACITY && t.blocked_finish==TITCHY_CAPACITY);
            check(!pop(enc,1,TITCHY_CAPACITY).chunks && same(s,stats(enc)));
        }
        if (s.ready_packets && drain()) t.emissions.push_back(i+1);
    }
    check(titchy_stream_finish(enc)==TITCHY_OK);
    check(drain() && packets>t.emissions.size());
    t.end=stats(enc);
    check(t.end.finished && t.end.samples==count);
    t.push_after_finish=titchy_stream_push(enc,0);
    t.finish_after_finish=titchy_stream_finish(enc);
    check(t.push_after_finish==TITCHY_INVALID && t.finish_after_finish==TITCHY_INVALID);
    for (size_t i=0; i<4; ++i) wire[17+i]=uint8_t(packets>>(8*i));
    return wire;
}
void write_stream() {
    auto input=load("/inputs/input",count*8);
    check(input.size()==count*8);
    auto enc=encoder(count);
    Trace trace,retry;
    auto wire=encode(enc.get(),input,trace,true);
    check(titchy_stream_encoder_reset(enc.get())==TITCHY_OK && !stats(enc.get()).samples);
    auto again=encode(enc.get(),input,retry,false);
    check(again==wire && retry.emissions==trace.emissions);
    auto empty=encoder(0);
    int overflow=titchy_stream_push(empty.get(),1), failed=titchy_stream_finish(empty.get());
    check(overflow==TITCHY_INVALID && failed==TITCHY_INVALID);
    check(titchy_stream_encoder_reset(empty.get())==TITCHY_OK && titchy_stream_finish(empty.get())==TITCHY_OK &&
        !pop(empty.get()).chunks);
    check(!trace.emissions.empty());
    save("archive",wire); save("config",config_wire());
    std::cout << "{\"emitted_after_push\":[";
    for (size_t i=0;i<trace.emissions.size();++i) std::cout << (i?",":"") << trace.emissions[i];
    std::cout << "],\"finished_samples\":" << trace.end.samples << ",\"max_active_bases\":" << trace.active
              << ",\"max_ready_packets_observed\":" << trace.ready << ",\"dictionary_bases\":" << trace.end.dictionary_bases
              << ",\"reset_identical\":true,\"statuses\":{\"blocked_push\":" << trace.blocked_push
              << ",\"blocked_finish\":" << trace.blocked_finish << ",\"small_pop\":2,\"push_after_finish\":"
              << trace.push_after_finish << ",\"finish_after_finish\":" << trace.finish_after_finish
              << ",\"empty_session_overflow\":" << overflow << ",\"finish_after_overflow\":" << failed << "}}\n";
}
Values packet(titchy_stream_decoder *dec,const Packet &p,size_t cap=target*chunk,int expected=TITCHY_OK) {
    Values out(cap);
    size_t n=99;
    check(titchy_stream_decode_packet(dec,p.wire.data(),p.wire.size(),p.chunks,out.data(),cap,&n)==expected);
    check(n==(expected==TITCHY_OK?p.chunks*chunk:0) && n<=cap);
    out.resize(n);
    return out;
}
void read_stream() {
    const auto wire=load("/inputs/archive",limit), config=load("/inputs/config",32);
    check(config==config_wire() && wire.size()>=21 && std::memcmp(wire.data(),"TSTR\1",5)==0);
    uint64_t bits=get(config,12,8);
    double threshold;
    std::memcpy(&threshold,&bits,8);
    const titchy_config conf{uint8_t(get(config,4,1)),uint8_t(get(config,5,1)),uint16_t(get(config,6,2)),
        uint8_t(get(config,8,1)),threshold,get(config,20,8)};
    const size_t cap=get(config,10,2);
    check(get(wire,5,1)==conf.bits_per_sample && get(wire,6,1)==conf.samples_per_chunk &&
          get(wire,7,2)==conf.chunks_per_split && get(wire,9,8)==count);
    const size_t np=get(wire,17,4);
    check(np>1 && np<=padded/chunk);
    size_t pos=21,total=0;
    std::vector<Packet> packets;
    for (size_t i=0;i<np;++i) {
        const size_t nch=get(wire,pos,2), len=get(wire,pos+2,4);
        pos+=6;
        check(nch && nch<=cap && len && len<=wire.size()-pos && (total+=nch)<=padded/chunk);
        packets.push_back({nch,Bytes(wire.begin()+pos,wire.begin()+pos+len)});
        pos+=len;
    }
    check(pos==wire.size() && total==padded/chunk);
    auto dec=decoder(conf,padded);
    Values values;
    packet(dec.get(),packets.front(),1,TITCHY_CAPACITY);
    for (const auto &p:packets) {
        auto block=packet(dec.get(),p);
        values.insert(values.end(),block.begin(),block.end());
    }
    check(values.size()==padded && std::all_of(values.begin()+count,values.end(),[](auto x){return x==0;}));
    check(titchy_stream_decoder_reset(dec.get())==TITCHY_OK);
    auto cut=packets.front(); check(cut.wire.size()>1); cut.wire.pop_back();
    packet(dec.get(),cut,target*chunk,TITCHY_STREAM);
    packet(dec.get(),packets.front(),target*chunk,TITCHY_INVALID);
    check(titchy_stream_decoder_reset(dec.get())==TITCHY_OK);
    const auto first=packet(dec.get(),packets.front());
    check(std::equal(first.begin(),first.end(),values.begin()));
    auto quota=decoder(conf,count);
    for (size_t i=0;i<np-1;++i) packet(quota.get(),packets[i]);
    packet(quota.get(),packets.back(),target*chunk,TITCHY_CAPACITY);
    packet(quota.get(),packets.back(),target*chunk,TITCHY_INVALID);
    Bytes out;
    for (size_t i=0;i<count;++i) put(out,values[i],8);
    save("v",out);
    std::cout << "{\"true_values\":" << count << ",\"padded_values\":" << values.size()
              << ",\"decoder_reset_checked\":true,\"statuses\":{\"small_output_retry\":2,\"truncated_packet\":4,"
              << "\"decode_after_corruption\":1,\"tail_quota\":2,\"decode_after_quota\":1}}\n";
}
}
int main(int argc,char **argv) {
    try {
        check(argc==2);
        const std::string mode=argv[1];
        if (mode=="encode") write_stream();
        else if (mode=="decode") read_stream();
        else check(false);
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
