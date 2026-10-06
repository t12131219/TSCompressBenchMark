// SPDX-License-Identifier: NOASSERTION
#include "corad.hpp"
#include <fstream>
#include <iostream>
#include <limits>
extern "C" int corad_rank_descending(const double*,std::size_t,std::uint32_t*);
template<class T>std::vector<T> read(const std::string& path){std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("Cannot open input");auto n=f.tellg();if(n<0||static_cast<std::uint64_t>(n)>256ULL*1024*1024||n%sizeof(T))throw std::runtime_error("Input size invalid");std::vector<T> out(static_cast<std::size_t>(n)/sizeof(T));f.seekg(0);f.read(reinterpret_cast<char*>(out.data()),n);if(!f)throw std::runtime_error("Input read failed");return out;}
template<class T>void write(const std::string& p,const std::vector<T>& v){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(v.data()),static_cast<std::streamsize>(v.size()*sizeof(T)));if(!f)throw std::runtime_error("Output write failed");}
std::uint32_t number(const char* p){auto n=std::stoull(p);if(n>UINT32_MAX)throw std::runtime_error("Argument exceeds u32");return static_cast<std::uint32_t>(n);}
int main(int argc,char** argv){try{
    const std::uint16_t endian=1;if(*reinterpret_cast<const unsigned char*>(&endian)!=1||!std::numeric_limits<double>::is_iec559||sizeof(double)!=8)throw std::runtime_error("Raw diagnostic arrays require little-endian binary64");
    if(argc==2&&std::string(argv[1])=="backend"){std::cout<<tristan::backend_info()<<'\n';return 0;}
    if(argc==3&&std::string(argv[1])=="rng"){write(argv[2],tristan::rng_trace(0));return 0;}
    if(argc==4&&std::string(argv[1])=="rank"){auto scores=read<double>(argv[2]);std::vector<std::uint32_t> order(scores.size());if(corad_rank_descending(scores.data(),scores.size(),order.data()))throw std::runtime_error("Rank size must be1..256");write(argv[3],order);return 0;}
    if(argc==8&&std::string(argv[1])=="correlate"){
        auto x=read<double>(argv[2]);auto rows=std::stoull(argv[3]);auto channels=number(argv[4]);if(rows>1048576||channels>256||rows*channels!=x.size())throw std::runtime_error("Input shape mismatch");
        auto selection=corad::correlate(x.data(),rows,channels,number(argv[5]),std::stod(argv[6]));std::string p=argv[7];write(p+".correlations.bin",selection.correlations);write(p+".order.bin",selection.order);write(p+".references.bin",selection.references);return 0;
    }
    if(argc==4&&std::string(argv[1])=="decode"){auto f=read<std::uint8_t>(argv[2]);auto d=corad::decode(f.data(),f.size());write(argv[3],d.values);std::cout<<"decoded="<<d.values.size()<<" final_bits="<<d.accounting.final_bits()<<'\n';return 0;}
    if(argc==13&&std::string(argv[1])=="encode"){
        auto x=read<double>(argv[2]);auto rows=std::stoull(argv[3]);auto channels=number(argv[4]);if(rows>1048576||channels>256||rows*channels!=x.size())throw std::runtime_error("Input shape mismatch");
        corad::Config c;c.length=number(argv[5]);c.atoms=number(argv[6]);c.nonzeros=number(argv[7]);c.solver=static_cast<corad::Solver>(number(argv[8]));c.seed=number(argv[9]);c.alpha=std::stod(argv[10]);c.threshold=std::stod(argv[11]);corad::Trace trace;auto frame=corad::encode(x.data(),rows,channels,c,{},&trace);std::string p=argv[12];write(p,frame);
        write(p+".normalized.bin",trace.normalized);write(p+".dictionary.bin",trace.dictionary);write(p+".coefficients.bin",trace.coefficients);write(p+".means.bin",trace.means);write(p+".scales.bin",trace.scales);write(p+".costs.bin",trace.costs);write(p+".correlations.bin",trace.selection.correlations);write(p+".order.bin",trace.selection.order);write(p+".references.bin",trace.selection.references);std::cout<<"bytes_written="<<frame.size()<<'\n';return 0;
    }
    throw std::runtime_error("encode input rows channels length atoms nonzeros solver seed alpha threshold frame | decode frame output | correlate input rows channels length threshold prefix | rank scores output | backend | rng output");
}catch(const corad::Error& e){std::cerr<<"CORAD_ERROR "<<static_cast<int>(e.code)<<": "<<e.what()<<'\n';return 2;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 3;}}
