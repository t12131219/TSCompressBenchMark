// Direct SElf* C ABI control, separate from the benchmark plugin and worker.
#include "selfstar.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using B = std::vector<uint8_t>;
using Ctx = std::unique_ptr<sf_c, decltype(&sf_c_destroy)>;
constexpr size_t Block=512, Workspace=25000, Limit=256*1024;
constexpr std::array<uint8_t,8> Magic{'B','M','K','S','E','L',1,0};
constexpr std::array<size_t,4> Schedule{1,7,63,121};
void need(bool ok) { if (!ok) throw std::runtime_error("SElf* ordered control assertion"); }
Ctx ctx(unsigned width) {
    Ctx c(sf_c_create(SF_SELF_STAR,static_cast<sf_dtype>(width)),sf_c_destroy);
    need(bool(c)); return c;
}
B read(const char *path) {
    std::ifstream in(path,std::ios::binary|std::ios::ate);
    const auto n=in.tellg(); need(in.good() && n>=0 && n<=static_cast<std::streamoff>(Limit));
    B b(static_cast<size_t>(n)); in.seekg(0);
    if (!b.empty()) need(bool(in.read(reinterpret_cast<char*>(b.data()),n)));
    return b;
}
void write(const char *path,const B &b) {
    std::ofstream out(path,std::ios::binary);
    out.write(reinterpret_cast<const char*>(b.data()),static_cast<std::streamsize>(b.size()));
    out.close(); need(bool(out));
}
void put(B &b,size_t n,uint64_t x) { for(size_t i=0;i<n;++i) b.push_back(static_cast<uint8_t>(x>>(i*8))); }
uint64_t get(const B &b,size_t at,size_t n) {
    need(at<=b.size() && n<=b.size()-at); uint64_t v=0;
    for(size_t i=0;i<n;++i) v|=uint64_t(b[at+i])<<(i*8);
    return v;
}
size_t bytes(size_t bits) { return (bits+7)/8; }
struct Record { size_t n{}, bits{}, before{}; B payload, prefix; std::vector<size_t> adds, progress; };
struct Frame { unsigned width{}; size_t count{}; B schema; std::vector<Record> recs; };
Frame frame(const B &wire) {
    need(wire.size()>=32 && std::equal(Magic.begin(),Magic.end(),wire.begin()));
    Frame f;
    const auto dtype=get(wire,8,4),count=get(wire,12,8),schema=get(wire,20,4),payload=get(wire,24,8);
    need((dtype==9 || dtype==10) && count>0 && count<=4096 && schema<=65536 && schema<=wire.size()-32 &&
         payload==wire.size()-32-schema);
    f.width=dtype==9?32:64; f.count=count;
    size_t pos=32+schema;
    f.schema.assign(wire.begin()+32,wire.begin()+pos);
    for(size_t off=0;off<count;off+=Block) {
        Record r; r.n=std::min(Block,count-off); r.bits=get(wire,pos,4); pos+=4;
        need(r.bits && r.bits<=(r.n+1)*(f.width+28)+395 && bytes(r.bits)<=wire.size()-pos);
        r.payload.assign(wire.begin()+pos,wire.begin()+pos+bytes(r.bits)); pos+=bytes(r.bits);
        need(!(r.bits%8) || !(r.payload.back()&((1u<<(8-r.bits%8))-1)));
        f.recs.push_back(std::move(r));
    }
    need(pos==wire.size()); return f;
}
template<class T> std::vector<T> typed(const B &b) {
    need(b.size()%sizeof(T)==0); std::vector<T> v(b.size()/sizeof(T));
    if (!v.empty()) std::memcpy(v.data(),b.data(),b.size());
    return v;
}
template<class T> Record pack(sf_c *c,const T *p,size_t n,bool live) {
    Record r; r.n=n; r.payload.resize(Workspace);
    if (!live) need(sf_c_encode(c,p,n,r.payload.data(),Workspace,&r.bits)==SF_OK);
    else {
        need(sf_c_begin(c,r.payload.data(),Workspace)==SF_OK);
        sf_progress initial{};
        need(sf_c_progress(c,&initial)==SF_OK && !initial.count && !initial.bits && !initial.deferred_values && initial.phase==1);
        size_t o=0, k=0;
        while(o<n) {
            auto take=std::min(n-o,k<Schedule.size()?Schedule[k]:n);
            need(sf_c_add(c,p+o,take)==SF_OK); o+=take; ++k;
            sf_progress progress{};
            need(sf_c_progress(c,&progress)==SF_OK && progress.count==o && progress.bits>r.before &&
                 !progress.deferred_values && progress.phase==1);
            r.before=progress.bits; r.adds.push_back(o); r.progress.push_back(r.before);
        }
        r.prefix.assign(r.payload.begin(),r.payload.begin()+bytes(r.before));
        need(sf_c_finish(c,&r.bits)==SF_OK && r.bits>r.before);
        sf_progress end{};
        need(sf_c_progress(c,&end)==SF_OK && end.count==n && end.bits==r.bits && !end.deferred_values && end.phase==0);
    }
    need(r.bits>0 && bytes(r.bits)<=Workspace); r.payload.resize(bytes(r.bits)); return r;
}
template<class T> void unpack(sf_c *c,const Record &r,T *dest) {
    int has=-1;
    need(sf_c_read_begin(c,r.payload.data(),r.payload.size(),r.bits,r.n)==SF_OK);
    for(size_t i=0;i<r.n;++i) need(sf_c_next(c,dest+i,&has)==SF_OK && has==1);
    sf_progress before{},end{};
    T last{};
    need(sf_c_progress(c,&before)==SF_OK && before.count==r.n && before.bits<r.bits && before.phase==2 &&
         sf_c_next(c,&last,&has)==SF_OK && !has && sf_c_progress(c,&end)==SF_OK && end.count==r.n && end.bits==r.bits && end.phase==0);
}
void nums(const std::vector<size_t>& a) {
    std::printf("["); for(size_t i=0;i<a.size();++i) std::printf("%s%zu",i?",":"",a[i]); std::printf("]");
}
template<class T> void encode(bool live,const B &raw,const B &schema,const char *dest) {
    auto values=typed<T>(raw); need(!values.empty() && values.size()<=4096 && schema.size()<=65536);
    auto c=ctx(sizeof(T)*8);
    std::vector<Record> recs;
    B payload;
    for(size_t i=0;i<values.size();i+=Block) {
        auto r=pack(c.get(),values.data()+i,std::min(Block,values.size()-i),live);
        put(payload,4,r.bits); payload.insert(payload.end(),r.payload.begin(),r.payload.end());
        recs.push_back(std::move(r));
    }
    B out(Magic.begin(),Magic.end());
    put(out,4,sizeof(T)==4?9:10); put(out,8,values.size()); put(out,4,schema.size()); put(out,8,payload.size());
    out.insert(out.end(),schema.begin(),schema.end()); out.insert(out.end(),payload.begin(),payload.end());
    write(dest,out);
    std::printf("{\"rows\":%zu,\"width\":%zu,\"mode\":\"%s\",\"blocks\":[", values.size(),sizeof(T)*8,live?"live":"batch");
    for(size_t i=0;i<recs.size();++i) {
        const auto &r=recs[i];
        std::printf("%s{\"n\":%zu,\"bits\":%zu,\"before_finish_bits\":%zu,\"add_counts\":",i?",":"",r.n,r.bits,r.before);
        nums(r.adds); std::printf(",\"add_bits\":"); nums(r.progress); std::printf("}");
    }
    std::printf("]}\n");
}
template<class T> void decode(const Frame &f,const char *raw) {
    auto c=ctx(f.width); B result;
    for(const auto &r:f.recs) {
        std::vector<T> values(r.n); unpack(c.get(),r,values.data());
        const auto *p=reinterpret_cast<const uint8_t*>(values.data()); result.insert(result.end(),p,p+r.n*sizeof(T));
    }
    write(raw,result);
    std::vector<size_t> bits; for(const auto &r:f.recs) bits.push_back(r.bits);
    std::printf("{\"rows\":%zu,\"width\":%u,\"drained_bits\":",f.count,f.width); nums(bits); std::printf("}\n");
}
template<class T> void exercise(const Frame &f,const B &raw) {
    const auto values=typed<T>(raw);
    need(values.size()==f.count && f.recs.size()>1);
    auto enc=ctx(f.width),dec=ctx(f.width);
    const auto &a=f.recs[0], &b=f.recs[1];
    std::vector<T> scratch(std::max(a.n,b.n));
    auto skip=sf_c_decode(dec.get(),b.payload.data(),b.payload.size(),b.bits,scratch.data(),b.n);
    need(skip==SF_CORRUPT && sf_c_reset(dec.get())==SF_OK);
    unpack(dec.get(),a,scratch.data());
    need(!std::memcmp(values.data(),scratch.data(),a.n*sizeof(T)));
    unpack(dec.get(),b,scratch.data());
    need(!std::memcmp(values.data()+a.n,scratch.data(),b.n*sizeof(T)));
    auto fresh=pack(enc.get(),values.data()+a.n,b.n,false);
    need(fresh.bits!=b.bits || fresh.payload!=b.payload);
    Record partial;
    for(int round=0;round<2;++round) {
        need(sf_c_reset(enc.get())==SF_OK);
        size_t off=0;
        for(const auto &r:f.recs) {
            auto got=pack(enc.get(),values.data()+off,r.n,round==1);
            need(got.bits==r.bits && got.payload==r.payload);
            if(round==1 && off==a.n) partial=std::move(got);
            off+=r.n;
        }
    }
    need(sf_c_reset(dec.get())==SF_OK);
    unpack(dec.get(),a,scratch.data());
    need(sf_c_read_begin(dec.get(),partial.prefix.data(),partial.prefix.size(),partial.before,b.n)==SF_OK);
    int has=-1;
    for(size_t i=0;i<b.n;++i) need(sf_c_next(dec.get(),scratch.data()+i,&has)==SF_OK && has==1);
    need(!std::memcmp(values.data()+a.n,scratch.data(),b.n*sizeof(T)));
    T tail{};
    auto incomplete=sf_c_next(dec.get(),&tail,&has), after=sf_c_next(dec.get(),&tail,&has);
    need(incomplete==SF_CORRUPT && after==SF_STATE && sf_c_reset(dec.get())==SF_OK);
    size_t off=0;
    for(const auto &r:f.recs) {
        unpack(dec.get(),r,scratch.data()); need(!std::memcmp(values.data()+off,scratch.data(),r.n*sizeof(T))); off+=r.n;
    }
    std::printf("{\"skip_prefix\":%d,\"prefix_rows\":%zu,\"prefix_body_bytes\":%zu,\"prefix_header_bytes\":4,"
                "\"before_finish_bits\":%zu,\"partial_rows\":%zu,\"partial_terminal\":%d,\"after_failure\":%d,"
                "\"reset_replay\":true,\"fresh_second_differs\":true}\n",
                skip,a.n,a.payload.size(),partial.before,b.n,incomplete,after);
}
template<class T> void limits(const B &raw) {
    auto p=typed<T>(raw); need(p.size()>1000);
    auto c=ctx(sizeof(T)*8),d=ctx(sizeof(T)*8);
    B workspace(Workspace); size_t bits=0;
    const uint64_t q=sizeof(T)==4?0x7fc00123:0x7ff8000000000123ULL;
    const uint64_t s=sizeof(T)==4?0x7f800123:0x7ff0000000000123ULL;
    T nan[2]{}; std::memcpy(&nan[0],&q,sizeof(T)); std::memcpy(&nan[1],&s,sizeof(T));
    for(auto v:{std::pair{p.data(),size_t(0)},std::pair{p.data(),size_t(1001)},std::pair{nan,size_t(1)},std::pair{nan+1,size_t(1)}}) {
        need(sf_c_reset(c.get())==SF_OK && sf_c_encode(c.get(),v.first,v.second,workspace.data(),Workspace,&bits)==SF_INVALID);
    }
    need(sf_c_reset(c.get())==SF_OK);
    auto max=pack(c.get(),p.data(),1000,false);
    need(sf_c_reset(c.get())==SF_OK);
    auto live=pack(c.get(),p.data(),1000,true);
    need(live.bits==max.bits && live.payload==max.payload);
    std::vector<T> out(1000); unpack(d.get(),max,out.data()); need(!std::memcmp(out.data(),p.data(),sizeof(T)*1000));
    need(sf_c_reset(c.get())==SF_OK && sf_c_begin(c.get(),workspace.data(),Workspace)==SF_OK &&
         sf_c_finish(c.get(),&bits)==SF_INVALID && sf_c_add(c.get(),p.data(),1001)==SF_INVALID &&
         sf_c_add(c.get(),nan,1)==SF_INVALID && sf_c_add(c.get(),nan+1,1)==SF_INVALID &&
         sf_c_add(c.get(),p.data(),1000)==SF_OK && sf_c_add(c.get(),p.data()+1000,1)==SF_INVALID &&
         sf_c_finish(c.get(),&bits)==SF_OK && bits==max.bits);
    need(sf_c_reset(c.get())==SF_OK && sf_c_begin(c.get(),workspace.data(),1)==SF_OK &&
         sf_c_add(c.get(),p.data(),8)==SF_CAPACITY && sf_c_finish(c.get(),&bits)==SF_STATE && sf_c_reset(c.get())==SF_OK);
    need(pack(c.get(),p.data(),1000,true).payload==max.payload);
    std::printf("{\"max_block_rows\":1000,\"max_block_bits\":%zu,\"workspace_bytes\":25000,"
                "\"batch_invalid\":[1,1,1,1],\"live_invalid\":[1,1,1,1,1],\"capacity\":2,\"finish_after_capacity\":5,\"reset_recovers\":true}\n",max.bits);
}
}
int main(int argc,char **argv) {
    try {
        const std::string op=argc>1?argv[1]:"";
        if (op=="batch" || op=="live" || op=="limits") {
            need(argc==(op=="limits"?4:6));
            const std::string w=argv[2]; need(w=="32" || w=="64");
            auto raw=read(argv[3]);
            if (op=="limits") { if(w=="32") limits<float>(raw); else limits<double>(raw); }
            else if (w=="32") encode<float>(op=="live",raw,read(argv[4]),argv[5]);
            else encode<double>(op=="live",raw,read(argv[4]),argv[5]);
        } else if (op=="decode" || op=="exercise") {
            need(argc==4); auto f=frame(read(argv[2]));
            if (op=="decode") { if(f.width==32) decode<float>(f,argv[3]); else decode<double>(f,argv[3]); }
            else if(f.width==32) exercise<float>(f,read(argv[3])); else exercise<double>(f,read(argv[3]));
        } else need(false);
        return 0;
    } catch(const std::exception &e) { std::fprintf(stderr,"%s\n",e.what()); return 2; }
}
