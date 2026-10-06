// SPDX-License-Identifier: NOASSERTION
#include "tristan.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <cstring>

template<class T> std::vector<T> read(const std::string& path){
    std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("Cannot open input");auto n=f.tellg();
    if(n<0||static_cast<std::uint64_t>(n)>256ULL*1024*1024||n%sizeof(T))throw std::runtime_error("Invalid input file size");
    std::vector<T> out(static_cast<std::size_t>(n)/sizeof(T));f.seekg(0);f.read(reinterpret_cast<char*>(out.data()),n);if(!f)throw std::runtime_error("Input read failed");return out;
}
template<class T>void write(const std::string& p,const std::vector<T>& v){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(v.data()),static_cast<std::streamsize>(v.size()*sizeof(T)));if(!f)throw std::runtime_error("Output write failed");}
std::uint32_t number(const char* s){auto x=std::stoull(s);if(x>UINT32_MAX)throw std::runtime_error("Argument exceeds u32");return static_cast<std::uint32_t>(x);}
int main(int argc,char** argv){try{
    const std::uint16_t endian=1;
    if(*reinterpret_cast<const unsigned char*>(&endian)!=1||!std::numeric_limits<double>::is_iec559||sizeof(double)!=8)throw std::runtime_error("Diagnostic raw files require little-endian IEEE754 binary64 host");
    if(argc==2&&std::string(argv[1])=="backend"){std::cout<<tristan::backend_info()<<'\n';return 0;}
    if(argc==3&&std::string(argv[1])=="rng"){write(argv[2],tristan::rng_trace(0));return 0;}
    if(argc==6&&std::string(argv[1])=="debug-lars"){
        auto g=read<double>(argv[2]),q=read<double>(argv[3]);std::vector<std::vector<double>> records;
        auto coefficients=tristan::debug_lars(g,q,number(argv[4]),records);std::string p=argv[5];write(p+".coefficients.bin",coefficients);
        for(std::size_t i=0;i<records.size();++i)write(p+"."+std::to_string(i)+".bin",records[i]);return 0;
    }
    if(argc==4&&std::string(argv[1])=="decode"){auto f=read<std::uint8_t>(argv[2]);auto out=tristan::decode(f.data(),f.size());write(argv[3],out.values);std::cout<<"decoded="<<out.values.size()<<" final_bits="<<out.accounting.final_bits()<<'\n';return 0;}
    if(argc==12&&std::string(argv[1])=="encode"){
        auto input=read<double>(argv[2]);auto rows=std::stoull(argv[3]);auto channels=number(argv[4]);tristan::Config c;c.length=number(argv[5]);c.atoms=number(argv[6]);c.nonzeros=number(argv[7]);c.solver=static_cast<tristan::Solver>(number(argv[8]));c.seed=number(argv[9]);c.alpha=std::stod(argv[10]);
        if(rows>1048576||channels>256||rows*channels!=input.size())throw std::runtime_error("Input shape mismatch");
        tristan::Trace trace;auto f=tristan::encode(input.data(),rows,channels,c,{},&trace);std::string p=argv[11];write(p,f);
        write(p+".normalized.bin",trace.normalized);write(p+".dictionary.bin",trace.dictionary);write(p+".coefficients.bin",trace.coefficients);write(p+".means.bin",trace.means);write(p+".scales.bin",trace.scales);write(p+".costs.bin",trace.costs);
        for(std::size_t i=0;i<trace.learning_snapshots.size();++i)write(p+".learning-"+std::to_string(i)+".bin",trace.learning_snapshots[i]);
        std::cout<<"bytes_written="<<f.size()<<"\n";return 0;
    }
    if(argc==10&&std::string(argv[1])=="sparse"){
        auto x=read<double>(argv[2]),d=read<double>(argv[3]);auto rows=std::stoull(argv[4]);tristan::Config c;c.length=number(argv[5]);c.atoms=number(argv[6]);c.nonzeros=number(argv[7]);c.solver=static_cast<tristan::Solver>(number(argv[8]));write(argv[9],tristan::sparse(x,rows,d,c));return 0;
    }
    throw std::runtime_error("Usage: encode input rows channels length atoms nonzeros solver seed alpha output | decode frame output | rng output | sparse input dictionary samples length atoms nonzeros solver output");
}catch(const tristan::Error& e){std::cerr<<"TRISTAN_ERROR "<<static_cast<int>(e.code)<<": "<<e.what()<<'\n';return 2;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 3;}}
