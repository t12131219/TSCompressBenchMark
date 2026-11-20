// Corpus harness for the frozen C11 Gorilla backend. GTV1 is a harness envelope,
// not a change to the native XORChunk bytes written by gorilla_c.
#include "gorilla.h"
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {
namespace fs = std::filesystem;
using Bytes = std::vector<uint8_t>;
using Clock = std::chrono::steady_clock;
constexpr size_t block = 512, cap = 16384;
const uint8_t magic[] = {'G','T','V','1',1,0,0,0};
using Enc = std::unique_ptr<g_encoder, decltype(&g_encoder_destroy)>;
using Iter = std::unique_ptr<g_iterator, decltype(&g_iterator_destroy)>;
void check(bool b, const char* msg) { if (!b) throw std::runtime_error(msg); }
void ok(g_status st, const char* msg) { if (st != G_OK) throw std::runtime_error(std::string(msg) + ": " + g_strerror(st)); }
uint64_t ns(Clock::time_point t) { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-t).count(); }
void read(std::istream& f, void* p, size_t n) { check(bool(f.read(static_cast<char*>(p), n)), "truncated Gorilla input"); }
void write(std::ostream& f, const void* p, size_t n) { check(bool(f.write(static_cast<const char*>(p), n)), "Gorilla write failed"); }
void end(std::istream& f) { check(f.peek() == std::char_traits<char>::eof() && f.eof() && !f.bad(), "trailing Gorilla input"); }
void close(std::ofstream& f) { f.close(); check(f.good(), "Gorilla close failed"); }
uint64_t get(const uint8_t* p, unsigned n) { uint64_t v=0; for(unsigned j=0;j<n;++j) v|=uint64_t(p[j])<<(8*j); return v; }
void le(std::ostream& f, uint64_t v, unsigned n) {
    uint8_t p[8]; for(unsigned j=0;j<n;++j) p[j]=uint8_t(v>>(8*j)); write(f,p,n);
}
uint64_t rd(std::istream& f, unsigned n) { uint8_t p[8]; read(f,p,n); return get(p,n); }
size_t geometry(uint64_t n, size_t cap_) { check(n>0 && n<=cap_, "Gorilla corpus geometry exceeds harness bound"); return size_t(n); }
size_t parse(std::string_view val, size_t cap_) {
    size_t n=0; auto r=std::from_chars(val.begin(),val.end(),n);
    check(r.ec==std::errc{} && r.ptr==val.end(),"invalid Gorilla geometry"); return geometry(n,cap_);
}
fs::path column(std::string_view folder,size_t c,const char* suffix) {
    std::ostringstream name; name<<"column-"<<std::setw(4)<<std::setfill('0')<<c<<suffix;
    return fs::path(folder)/name.str();
}
void header(std::ostream& f,size_t cols,size_t rows) { write(f,magic,8); le(f,cols,4); le(f,rows,8); }
void emit(std::ostream& f,const g_buffer& b,size_t n) {
    check(b.size>=2 && b.size<=cap && n==(size_t(b.data[0])<<8|b.data[1]),"invalid native frame extent");
    le(f,b.size,4); write(f,b.data,b.size);
}
Bytes payload(std::istream& f,size_t n) {
    const size_t z=rd(f,4); check(z>=2 && z<=cap,"invalid backing length");
    Bytes wire(z); read(f,wire.data(),wire.size());
    check(n==(size_t(wire[0])<<8|wire[1]),"native frame count differs"); return wire;
}
void pair(std::ostream& f,g_sample a) { le(f,uint64_t(a.timestamp),8); le(f,a.bits,8); }
Enc encoder() { g_encoder* out=nullptr; ok(g_encoder_create(block,&out),"encoder create"); check(out,"missing encoder"); return Enc(out,g_encoder_destroy); }
Iter iterator(const Bytes& b) { g_iterator* out=nullptr; ok(g_iterator_create(b.data(),b.size(),block,&out),"iterator create"); check(out,"missing iterator"); return Iter(out,g_iterator_destroy); }
void same(g_sample a,g_sample b) { check(a.timestamp==b.timestamp && a.bits==b.bits,"Gorilla sample differs"); }

void encode(std::string_view mode,std::string_view folder,size_t cols,size_t rows,std::string_view archive,std::string_view snapshots) {
    const bool state=mode=="append-resume";
    check(state==(snapshots!="-"),"unexpected Gorilla snapshots path");
    std::ifstream axis(fs::path(folder)/"axis.ms",std::ios::binary);
    check(axis.good(),"missing Gorilla input axis");
    std::vector<int64_t> times(rows);
    for(auto& t:times) { const auto a=rd(axis,8); std::memcpy(&t,&a,8); }
    end(axis); check(std::is_sorted(times.begin(),times.end()),"Gorilla axis not nondecreasing");
    std::ofstream out(fs::path(archive),std::ios::binary|std::ios::trunc), snaps;
    check(out.good(),"open Gorilla archive failed"); header(out,cols,rows);
    if(state) { snaps.open(fs::path(snapshots),std::ios::binary|std::ios::trunc); check(snaps.good(),"open snapshots failed"); header(snaps,cols,rows); }
    std::array<g_sample,block> plain{};
    std::array<uint8_t,block*8> raw{};
    std::cout<<"{\"cols\":"<<cols<<",\"rows\":"<<rows<<",\"units\":[";
    for(size_t c=0;c<cols;++c) {
        std::ifstream values(column(folder,c,".bin"),std::ios::binary); check(values.good(),"missing Gorilla value column");
        for(size_t start=0;start<rows;start+=block) {
            const size_t n=std::min(block,rows-start);
            read(values,raw.data(),n*8);
            for(size_t j=0;j<n;++j) plain[j]={times[start+j],get(raw.data()+8*j,8)};
            if(c||start) std::cout<<',';
            g_buffer frame{};
            if(state) {
                const auto cut=n/2;
                auto first=encoder();
                auto t=Clock::now(); ok(g_encoder_append(first.get(),plain.data(),cut),"prefix append"); auto prefix_ns=ns(t);
                size_t count=0,bits=0,workspace=0;
                ok(g_encoder_progress(first.get(),&count,&bits,&workspace),"prefix progress");
                check(count==cut,"Gorilla prefix extent differs");
                g_buffer snap{};
                t=Clock::now(); ok(g_encoder_snapshot(first.get(),&snap),"snapshot"); auto snapshot_ns=ns(t);
                std::unique_ptr<void,decltype(&g_free)> snap_owner(snap.data,g_free);
                emit(snaps,snap,cut);
                first.reset();
                auto resumed=encoder();
                t=Clock::now(); ok(g_encoder_resume(resumed.get(),snap.data,snap.size),"resume"); auto resume_ns=ns(t);
                size_t resumed_count=0,resumed_bits=0,resumed_workspace=0;
                ok(g_encoder_progress(resumed.get(),&resumed_count,&resumed_bits,&resumed_workspace),"resumed progress");
                check(resumed_count==cut && resumed_bits==bits && resumed_workspace==workspace,"resumed predictor progress differs");
                t=Clock::now(); ok(g_encoder_append(resumed.get(),plain.data()+cut,n-cut),"tail append"); auto tail_ns=ns(t);
                t=Clock::now(); ok(g_encoder_finish(resumed.get(),&frame),"resumed finish"); auto finish_ns=ns(t);
                std::unique_ptr<void,decltype(&g_free)> frame_owner(frame.data,g_free);
                g_buffer direct{}; ok(g_compress(plain.data(),n,&direct),"batch parity control");
                std::unique_ptr<void,decltype(&g_free)> direct_owner(direct.data,g_free);
                check(frame.size==direct.size && !std::memcmp(frame.data,direct.data,frame.size),"resumed result differs from batch bytes");
                emit(out,frame,n);
                std::cout<<'['<<c<<','<<start<<','<<n<<','<<frame.size<<','<<cut<<','<<snap.size<<','<<bits<<','<<workspace<<','
                         <<prefix_ns<<','<<snapshot_ns<<','<<resume_ns<<','<<tail_ns<<','<<finish_ns<<']';
            } else {
                const auto t=Clock::now(); ok(g_compress(plain.data(),n,&frame),"batch compress"); const auto elapsed=ns(t);
                std::unique_ptr<void,decltype(&g_free)> owner(frame.data,g_free);
                emit(out,frame,n);
                std::cout<<'['<<c<<','<<start<<','<<n<<','<<frame.size<<','<<elapsed<<']';
            }
        }
        end(values);
    }
    close(out); if(state) close(snaps);
    std::cout<<"]}\n";
}

void decode(std::string_view mode,std::string_view archive,std::string_view folder) {
    const bool snapshots=mode=="snapshots", iter=mode=="iterator";
    check(snapshots || iter || mode=="tv-batch" || mode=="append-resume","unknown Gorilla decode mode");
    std::ifstream in(fs::path(archive),std::ios::binary); uint8_t h[8]; read(in,h,8);
    check(!std::memcmp(h,magic,8),"Gorilla harness header differs");
    const size_t cols=geometry(rd(in,4),4096), rows=geometry(rd(in,8),1000000);
    std::cout<<"{\"cols\":"<<cols<<",\"rows\":"<<rows<<",\"units\":[";
    for(size_t c=0;c<cols;++c) {
        std::ofstream out(column(folder,c,".tv"),std::ios::binary|std::ios::trunc); check(out.good(),"open recovered TV failed");
        for(size_t start=0;start<rows;start+=block) {
            size_t n=std::min(block,rows-start); if(snapshots) n/=2;
            const auto wire=payload(in,n);
            if(c||start) std::cout<<',';
            std::cout<<'['<<c<<','<<start<<','<<n<<','<<wire.size();
            if(iter) {
                const auto t=Clock::now(); auto it=iterator(wire); const auto open_ns=ns(t);
                std::array<g_sample,block> p{};
                int present=0; g_sample s{};
                const auto d=Clock::now();
                for(size_t j=0;j<n;++j) { ok(g_iterator_next(it.get(),&p[j],&present),"iterator next"); check(present,"early iterator EOF"); }
                ok(g_iterator_next(it.get(),&s,&present),"iterator drain"); check(!present,"late iterator EOF");
                const auto drain_ns=ns(d);
                for(size_t j=0;j<n;++j) pair(out,p[j]);
                const auto target=p[n/2].timestamp;
                const auto* first=std::lower_bound(p.data(),p.data()+n,target,[](g_sample a,int64_t b){return a.timestamp<b;});
                ok(g_iterator_reset(it.get(),wire.data(),wire.size(),block),"iterator reset");
                const auto q=Clock::now(); ok(g_iterator_seek(it.get(),target,&s,&present),"forward seek"); const auto seek_ns=ns(q);
                check(present,"missing seek result"); same(s,*first);
                const auto answer=s;
                if(first+1<p.data()+n) {
                    ok(g_iterator_next(it.get(),&s,&present),"next after seek"); check(present,"missing next after seek"); same(s,*(first+1));
                    ok(g_iterator_seek(it.get(),target,&s,&present),"seek cannot rewind"); check(present,"lost current sample"); same(s,*(first+1));
                }
                ok(g_iterator_seek(it.get(),std::numeric_limits<int64_t>::max(),&s,&present),"seek to end");
                check(bool(present)==(p[n-1].timestamp==std::numeric_limits<int64_t>::max()),"seek end result differs");
                ok(g_iterator_next(it.get(),&s,&present),"validate seek trailer"); check(!present,"seek trailer differs");
                std::cout<<','<<open_ns<<','<<drain_ns<<','<<seek_ns<<','<<target<<','<<answer.timestamp<<','<<answer.bits;
            } else {
                g_array decoded{};
                const auto t=Clock::now(); ok(g_decompress(wire.data(),wire.size(),block,&decoded),"Gorilla decompress"); const auto elapsed=ns(t);
                std::unique_ptr<void,decltype(&g_free)> owner(decoded.data,g_free);
                check(decoded.count==n,"Gorilla recovered count differs");
                for(size_t j=0;j<n;++j) pair(out,decoded.data[j]);
                std::cout<<','<<elapsed;
            }
            std::cout<<']';
        }
        close(out);
    }
    end(in); std::cout<<"]}\n";
}
}

int main(int argc,char** argv) {
    try {
        check(argc>=3,"Gorilla control operation missing");
        const std::string_view op=argv[1],mode=argv[2];
        if(op=="encode") {
            check(argc==8 && (mode=="tv-batch" || mode=="append-resume" || mode=="iterator"),"invalid Gorilla encode arguments");
            encode(mode,argv[3],parse(argv[4],4096),parse(argv[5],1000000),argv[6],argv[7]);
        } else {
            check(op=="decode" && argc==5,"invalid Gorilla decode arguments");
            decode(mode,argv[3],argv[4]);
        }
        return std::cout.good()?0:1;
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
