#include "deepzip/deepzip.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>

using namespace deepzip;
static Bytes read(const std::string& path,std::size_t max=128*1024*1024) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f) throw std::runtime_error("cannot open input: "+path);
    auto size=f.tellg();
    if(size<0 || static_cast<std::uint64_t>(size)>max) throw std::runtime_error("input exceeds CLI resource limit");
    Bytes b(static_cast<std::size_t>(size)); f.seekg(0);
    if(!b.empty() && !f.read(reinterpret_cast<char*>(b.data()),size)) throw std::runtime_error("input read failed");
    return b;
}
static void write(const std::string& path,const Bytes& bytes) {
    std::ofstream f(path,std::ios::binary|std::ios::trunc);
    if(!f || (!bytes.empty() && !f.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()))))
        throw std::runtime_error("output write failed: "+path);
}
int main(int argc,char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="info") {
            std::cout<<"{\"version\":\""<<version()<<"\",\"cuda_available\":"<<(cuda_available()?"true":"false")<<"}\n";
            return 0;
        }
        if(argc==5 && std::string(argv[1])=="import") {
            auto model=Model::from_hdf5(argv[2],argv[3]); write(argv[4],model.serialize()); return 0;
        }
        if((argc==5 || argc==6) && std::string(argv[1])=="predict") {
            auto model=Model::load(read(argv[2])); auto raw=read(argv[3]);
            if(raw.size()%4) throw std::runtime_error("invalid context serialization");
            std::vector<std::uint32_t> x;
            for(std::size_t i=0;i<raw.size();i+=4) x.push_back(raw[i]|(std::uint32_t(raw[i+1])<<8)|(std::uint32_t(raw[i+2])<<16)|(std::uint32_t(raw[i+3])<<24));
            Backend backend=argc==6&&std::string(argv[5])=="cuda"?Backend::cuda:Backend::scalar;
            auto probabilities=model.predict(x,backend); Bytes out;
            for(float v:probabilities) {
                std::uint32_t bits;std::memcpy(&bits,&v,4);
                for(unsigned j=0;j<4;++j) out.push_back(static_cast<std::uint8_t>(bits>>(8*j)));
            }
            write(argv[4],out); return 0;
        }
        if((argc==7 || argc==8) && std::string(argv[1])=="encode") {
            auto model=Model::load(read(argv[2])); auto input=read(argv[3]);
            Config config;
            auto lanes=std::stoull(argv[5]);
            if(lanes>4096) throw std::runtime_error("invalid lanes");
            config.lanes=static_cast<std::uint32_t>(lanes);
            config.alphabet=read(argv[6],256);
            config.backend=argc==8&&std::string(argv[7])=="cuda"?Backend::cuda:Backend::scalar;
            auto result=compress(model,input,config);write(argv[4],result.bytes);
            const auto& l=result.ledger;
            std::cout<<"{\"bytes\":"<<result.bytes.size()<<",\"final_bits\":"<<l.final_bits()
                <<",\"metadata_bits\":"<<l.metadata_bits<<",\"model_bits\":"<<l.model_bits
                <<",\"lengths_bits\":"<<l.lengths_bits<<",\"entropy_bits\":"<<l.entropy_bits
                <<",\"padding_bits\":"<<l.padding_bits<<",\"checksum_bits\":"<<l.checksum_bits
                <<",\"backend\":\""<<(config.backend==Backend::cuda?"cuda":"scalar")<<"\"}\n";
            return 0;
        }
        if(argc==4 && std::string(argv[1])=="decode") {write(argv[3],decompress(read(argv[2])));return 0;}
        std::cerr<<"Usage: deepzip_cli info | import weights.hdf5 model_name model.dzm\n"
            <<"  predict model.dzm contexts.i32 probabilities.f32 [scalar|cuda]\n"
            <<"  encode model.dzm input output lanes alphabet.bytes [scalar|cuda]\n"
            <<"  decode input output\n";
        return 2;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
