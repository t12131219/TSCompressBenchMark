#include "dzip.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#include <stdexcept>
#include <thread>
#include <vector>
#if defined(__unix__)
#include <sys/mman.h>
#include <unistd.h>
#endif

namespace {
void check(bool ok,const char* message) {if(!ok) throw std::runtime_error(message);}
dzip::Bytes read(const char* path) {std::ifstream stream(path,std::ios::binary);check(bool(stream),"fixture open");return {std::istreambuf_iterator<char>(stream),std::istreambuf_iterator<char>()};}
template<class F> void rejected(F f) {bool failed=false;try {f();} catch(const std::invalid_argument&) {failed=true;}check(failed,"expected explicit rejection");}
std::uint32_t crc(const dzip::Bytes& bytes,std::size_t n) {std::uint32_t c=~std::uint32_t(0);for(std::size_t i=0;i<n;++i) {c^=bytes[i];for(unsigned j=0;j<8;++j)c=(c>>1)^(0xedb88320u&std::uint32_t(-std::int32_t(c&1)));}return ~c;}
void seal(dzip::Bytes& bytes) {auto value=crc(bytes,bytes.size()-4);for(unsigned i=0;i<4;++i) bytes[bytes.size()-4+i]=std::uint8_t(value>>(8*i));}
void put32(dzip::Bytes& bytes,std::size_t pos,std::uint32_t value) {for(unsigned i=0;i<4;++i)bytes[pos+i]=std::uint8_t(value>>(8*i));}
std::uint32_t adler(const dzip::Bytes& bytes,std::size_t pos,std::size_t n) {
    std::uint32_t a=1,b=0;for(std::size_t i=0;i<n;++i) {a=(a+bytes[pos+i])%65521;b=(b+a)%65521;}return (b<<16)|a;
}
}
int main(int argc,char** argv) {
    try {
        check(argc==3,"preflight requires alphabet-1 and alphabet-2 bootstrap fixtures");
        auto one=dzip::Network::load(read(argv[1])),two=dzip::Network::load(read(argv[2]));
        for(std::size_t n:{0u,1u,2u,63u,64u,65u,127u,128u,129u,191u,192u,193u,320u,321u}) {
            dzip::Bytes input(n,65);auto snapshot=input;
            auto result=dzip::compress(input,one,dzip::Mode::bootstrap);
            check(input==snapshot,"immutable input");check(dzip::decompress(result.bytes)==input,"boundary lossless roundtrip");
            check(result.bytes.size()<=dzip::compress_bound(input.size(),one),"conservative output bound");
            check(result.statistics.final_bits==result.statistics.metadata_bits+result.statistics.model_bits+result.statistics.payload_bits+result.statistics.checksum_bits,"FinalBits closure");
            dzip::Bytes storage(result.bytes.size()+16,0xa5);std::size_t required=0;
            check(!dzip::compress_to(input,one,dzip::Mode::bootstrap,storage.data()+8,result.bytes.size()-1,required),"capacity-minus-one rejected");
            check(std::all_of(storage.begin(),storage.end(),[](auto b){return b==0xa5;}),"undersize output unchanged");
            check(dzip::compress_to(input,one,dzip::Mode::bootstrap,storage.data()+8,result.bytes.size(),required),"exact capacity accepted");
            check(std::equal(storage.begin()+8,storage.end()-8,result.bytes.begin()),"capacity output equal");
            check(std::all_of(storage.begin(),storage.begin()+8,[](auto b){return b==0xa5;}) && std::all_of(storage.end()-8,storage.end(),[](auto b){return b==0xa5;}),"encode canaries");
            dzip::Bytes decoded(n+16,0xb6);
            if(n) {check(!dzip::decompress_to(result.bytes,decoded.data()+8,n-1,required),"decode capacity-minus-one rejected");check(std::all_of(decoded.begin(),decoded.end(),[](auto b){return b==0xb6;}),"undersize decode unchanged");}
            check(dzip::decompress_to(result.bytes,decoded.data()+8,n,required),"decode exact capacity accepted");
            check(std::equal(decoded.begin()+8,decoded.end()-8,input.begin()),"decoded capacity output equal");
        }
        dzip::Encoder encoder(two,dzip::Mode::bootstrap);dzip::Bytes input(193);
        for(std::size_t i=0;i<input.size();++i) input[i]=std::uint8_t(65+i%2);
        encoder.append(input.data(),67);encoder.append(input.data()+67,input.size()-67);
        auto first=encoder.finalize().bytes;check(encoder.finalize().bytes==first,"stable repeated finalize");
#if defined(__unix__)
        auto page=std::size_t(sysconf(_SC_PAGESIZE));auto accessible=((first.size()+page-1)/page)*page;
        auto mapped=static_cast<std::uint8_t*>(mmap(nullptr,accessible+page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
        check(mapped!=MAP_FAILED,"guard page allocation");check(mprotect(mapped+accessible,page,PROT_NONE)==0,"guard page protection");
        std::size_t guard_required=0;
        check(dzip::compress_to(input,two,dzip::Mode::bootstrap,mapped+accessible-first.size(),first.size(),guard_required),"exact output ending at guard page");
        check(dzip::decompress_to(first,mapped+accessible-input.size(),input.size(),guard_required),"exact decode ending at guard page");
        std::memcpy(mapped+accessible-input.size(),input.data(),input.size());
        dzip::Encoder borrowed(two,dzip::Mode::bootstrap);borrowed.append(mapped+accessible-input.size(),input.size());
        check(borrowed.finalize().bytes==first,"borrowed input ending at guard page");
        check(munmap(mapped,accessible+page)==0,"guard page release");
#endif
        rejected([&]{encoder.append(input.data(),1);});check(dzip::decompress(first)==input,"chunked append roundtrip");
        encoder.reset();check(encoder.size()==0,"clean reset");encoder.append(input.data(),input.size());check(encoder.finalize().bytes==first,"reset reproducible");
        dzip::Limits limit;limit.max_symbols=192;rejected([&]{dzip::compress(input,two,dzip::Mode::bootstrap,limit);});
        auto copy=two;std::vector<std::int32_t> contexts(64,0);check(copy.predict(contexts)==two.predict(contexts),"independent network copy");
        rejected([&]{two.predict(std::vector<std::int32_t>(63,0));});contexts[0]=2;rejected([&]{two.predict(contexts);});
        auto fixture=read(argv[2]);for(std::size_t n=0;n<fixture.size();n+=31) rejected([&]{dzip::Network::load(dzip::Bytes(fixture.begin(),fixture.begin()+std::ptrdiff_t(n)));});
        for(std::size_t n=0;n<first.size();n+=17) rejected([&]{dzip::decompress(dzip::Bytes(first.begin(),first.begin()+std::ptrdiff_t(n)));});
        std::mt19937 random(519);
        for(unsigned i=0;i<1000;++i) {
            auto corrupted=first;auto position=random()%(corrupted.size()-4);corrupted[position]^=std::uint8_t(1u<<(random()%8));
            rejected([&]{dzip::decompress(corrupted);});
            // Recompute outer integrity so inner parser/model validation is tested.
            if(position<44 || (position>=46 && position<74)) {seal(corrupted);try {dzip::decompress(corrupted);} catch(const std::invalid_argument&) {}}
        }
        // Deliberately repair both integrity layers to reach bounded entropy
        // parsing. A checksum alone is not a memory-safety boundary.
        const std::size_t model_start=46;std::uint64_t stored=0;
        for(unsigned b=0;b<8;++b)stored|=std::uint64_t(first[28+b])<<(8*b);
        for(unsigned i=0;i<500;++i) {
            auto corrupted=first;auto position=model_start+28+random()%(std::size_t(stored)-28);
            corrupted[position]^=std::uint8_t(1u<<(random()%8));
            put32(corrupted,model_start+20,adler(corrupted,model_start+28,std::size_t(stored)-28));
            put32(corrupted,model_start+24,adler(corrupted,model_start,24));seal(corrupted);
            try {dzip::decompress(corrupted);} catch(const std::invalid_argument&) {}
        }
        std::array<bool,4> passed{};std::vector<std::thread> threads;
        for(unsigned i=0;i<4;++i) threads.emplace_back([&,i]{try {auto local=two;passed[i]=dzip::decompress(dzip::compress(input,local,dzip::Mode::bootstrap).bytes)==input;} catch(...) {passed[i]=false;}});
        for(auto& thread:threads) thread.join();check(std::all_of(passed.begin(),passed.end(),[](bool value){return value;}),"four independent handles");
        auto combined=dzip::Network::create(2,dzip::ModelProfile::combined_cpu,23);threads.clear();passed.fill(false);
        for(unsigned i=0;i<4;++i) threads.emplace_back([&,i]{try {
            auto local=combined;auto frame=dzip::compress(input,local,dzip::Mode::combined);
            passed[i]=dzip::decompress(frame.bytes)==input && local.serialize()==combined.serialize();
        } catch(...) {passed[i]=false;}});
        for(auto& thread:threads)thread.join();
        check(std::all_of(passed.begin(),passed.end(),[](bool value){return value;}),"four independent online-training codecs");
        std::cout<<"Native boundaries, capacity/canaries, lifecycle, accounting, malformed frames/models and concurrency PASS\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
