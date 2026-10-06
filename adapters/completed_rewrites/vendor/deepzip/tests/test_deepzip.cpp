#include "deepzip/deepzip.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#ifdef __unix__
#include <sys/mman.h>
#include <unistd.h>
#endif

using namespace deepzip;
static void check(bool result,const char* message) {if(!result) throw std::runtime_error(message);}
int main(int argc,char** argv) {
    try {
        check(argc==2 || argc==3,"expected a four-symbol model path and optional cuda");
        std::ifstream file(argv[1],std::ios::binary);
        Bytes weights((std::istreambuf_iterator<char>(file)),{});
        auto model=Model::load(weights);
        check(model.alphabet_size()==4,"test model must have four symbols");
        Config config;config.lanes=4;config.alphabet={0,1,2,3};
        if(argc==3) {check(std::string(argv[2])=="cuda" && cuda_available(),"forced CUDA unavailable");config.backend=Backend::cuda;}
        for(std::size_t n:{0u,1u,2u,3u,4u,5u,63u,64u,65u,255u,256u,257u}) {
            Bytes input(n);for(std::size_t i=0;i<n;++i) input[i]=static_cast<std::uint8_t>((i*17+i/5)%4);
            auto saved=input;
            auto encoded=compress(model,input,config);
            check(input==saved,"input was modified");
            check(decompress(encoded.bytes)==input,"roundtrip failed");
            check(encoded.ledger.final_bits()==encoded.bytes.size()*8,"ledger failed");
            auto bound=compress_bound(model,n,config);
            Bytes guarded(bound+2,0xa5);
            auto used=compress_to(model,input,config,guarded.data()+1,bound);
            check(guarded.front()==0xa5 && guarded.back()==0xa5,"output canary changed");
            check(Bytes(guarded.begin()+1,guarded.begin()+1+used)==encoded.bytes,"buffer API differs");
            guarded.assign(bound+2,0xa5);
            bool rejected=false;
            try{compress_to(model,input,config,guarded.data()+1,bound-1);}catch(const Error& e){rejected=e.status==Status::insufficient_capacity;}
            check(rejected && std::all_of(guarded.begin(),guarded.end(),[](auto b){return b==0xa5;}),"bound-1 contract failed");
            Codec codec(model,config);
            codec.append(input.data(),input.size()/2);
            if(!input.empty()) codec.append(input.data()+input.size()/2,input.size()-input.size()/2);
            check(codec.finalize().bytes==encoded.bytes,"fragmented input differs");
            check(codec.finalize().bytes==encoded.bytes,"repeat finalize differs");
            rejected=false;try{codec.append(nullptr,0);}catch(const Error&){rejected=true;}
            check(rejected,"append after finalize accepted");
            codec.reset();codec.append(input.data(),input.size());
            check(codec.finalize().bytes==encoded.bytes,"reset differs");
            for(std::size_t cut:{0u,1u,7u,47u}) {
                Bytes truncated(encoded.bytes.begin(),encoded.bytes.begin()+std::min(cut,encoded.bytes.size()));
                rejected=false;try{decompress(truncated);}catch(const Error&){rejected=true;}
                check(rejected,"truncated container accepted");
            }
            auto corrupt=encoded.bytes;corrupt[corrupt.size()/2]^=1;
            rejected=false;try{decompress(corrupt);}catch(const Error&){rejected=true;}
            check(rejected,"corrupted container accepted");
        }
        auto c=cumulative({0.25f,0.5f,0.25f});
        check(c==std::vector<std::uint64_t>({0,2500001,7500002,10000003}),"NumPy cumulative semantics differ");
        for(const auto& invalid:std::vector<std::vector<float>>{{},{-1.0f},{2.0f}}) {
            bool rejected=false;try{cumulative(invalid);}catch(const Error&){rejected=true;}
            check(rejected,"invalid probability accepted");
        }
        for(auto invalid:std::vector<std::vector<std::uint64_t>>{{},{0,0},{1,2},{0,3,2}}) {
            bool rejected=false;try{encode_arithmetic({0},{invalid});}catch(const Error&){rejected=true;}
            check(rejected,"invalid cumulative table accepted");
        }
        bool rejected=false;try{model.predict({0,1});}catch(const Error&){rejected=true;}
        check(rejected,"invalid context shape accepted");
        rejected=false;try{model.predict(std::vector<std::uint32_t>(64,4));}catch(const Error&){rejected=true;}
        check(rejected,"out-of-alphabet context accepted");
        auto names=supported_models();
        for(auto name:{"FC_16bit","LSTM_multi_selu"})
            check(std::find(names.begin(),names.end(),name)==names.end(),"broken upstream constructor exposed");
        // Recomputed CRC permits malicious metadata to reach the parser.
        auto checksum=[](Bytes& bytes){
            std::uint32_t crc=0xffffffffu;
            for(std::size_t i=0;i<bytes.size()-4;++i) {crc^=bytes[i];for(unsigned j=0;j<8;++j) crc=(crc>>1)^(0xedb88320u&(0u-(crc&1)));}
            crc=~crc;for(unsigned j=0;j<4;++j) bytes[bytes.size()-4+j]=static_cast<std::uint8_t>(crc>>(j*8));
        };
        auto baseline=compress(model,{0,1,2},config).bytes;
        std::mt19937 rng(42);
        Limits limits;limits.max_input_bytes=1024;limits.max_lanes=8;
        for(unsigned iteration=0;iteration<2000;++iteration) {
            auto corrupt=baseline;
            std::size_t offset=rng()%(corrupt.size()-4);
            corrupt[offset]^=static_cast<std::uint8_t>(1u<<(rng()%8));
            checksum(corrupt);
            try {auto output=decompress(corrupt,limits);check(output==Bytes({0,1,2}),"forged CRC yielded wrong accepted input");}
            catch(const Error&) {}
            auto mutated=weights;
            mutated[rng()%mutated.size()]^=static_cast<std::uint8_t>(1u<<(rng()%8));
            try {auto unused=Model::load(mutated);(void)unused;}catch(const Error&) {}
        }
        for(std::size_t n=0;n<64;++n) {
            Bytes truncated(weights.begin(),weights.begin()+n);
            bool rejected=false;try{Model::load(truncated);}catch(const Error&){rejected=true;}
            check(rejected,"truncated model accepted");
        }
#ifdef __unix__
        auto page=static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
        auto mapping=mmap(nullptr,page*3,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        check(mapping!=MAP_FAILED,"guard page mapping failed");
        auto middle=static_cast<std::uint8_t*>(mapping)+page;
        check(mprotect(middle,page,PROT_READ|PROT_WRITE)==0,"guard page protection failed");
        middle[page-2]=1;middle[page-1]=2;
        Codec guarded(model,config);guarded.append(middle+page-2,2);
        check(decompress(guarded.finalize().bytes)==Bytes({1,2}),"guard page input failed");
        check(munmap(mapping,page*3)==0,"guard page unmap failed");
#endif
        std::cout<<"API boundaries, lifecycle, capacity, corruption, and accounting: PASS\n";
        return 0;
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
