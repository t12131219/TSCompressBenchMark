#include "walloc.hpp"
#include <ATen/detail/CUDAHooksInterface.h>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace walloc;
Bytes read(const char* p){std::ifstream f(p,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("fixture open");auto n=f.tellg();if(n<0||n>256*1024*1024)throw std::runtime_error("fixture size");Bytes b(n);f.seekg(0);if(n&&!f.read(reinterpret_cast<char*>(b.data()),n))throw std::runtime_error("fixture read");return b;}
int main(int argc,char** argv){try{
  if(argc!=5)throw std::runtime_error("MODEL INPUT LENGTH DEVICE");
  Codec::configure_cpu_threads(1);auto model=read(argv[1]),input=read(argv[2]);if(input.size()%4)throw std::runtime_error("partial float input");
  std::vector<float> x(input.size()/4);std::memcpy(x.data(),input.data(),input.size());auto L=std::stoull(argv[3]);std::string device=argv[4];
  auto sync=[&]{if(device=="cuda")at::detail::getCUDAHooks().deviceSynchronize(0);};
  auto now=[] {return std::chrono::steady_clock::now();};auto seconds=[](auto a,auto b){return std::chrono::duration<double>(b-a).count();};
  std::cout.precision(17);std::cout<<"{\"observations\":[";Ledger ledger;
  for(int i=-3;i<10;++i){sync();auto t0=now();Codec codec(model,device);sync();auto t1=now();
    auto frame=codec.encode(x.data(),x.size(),L,&ledger);sync();auto t2=now();
    auto y=Codec::decode(frame,device);sync();auto t3=now();if(y.values.size()!=x.size())throw std::runtime_error("length mismatch");
    if(i>=0){if(i)std::cout<<',';std::cout<<"{\"setup_seconds\":"<<seconds(t0,t1)<<",\"encode_seconds\":"<<seconds(t1,t2)<<",\"decode_seconds\":"<<seconds(t2,t3)<<",\"total_seconds\":"<<seconds(t0,t3)<<'}';}}
  std::cout<<"],\"model_bytes\":"<<ledger.model_bytes<<",\"payload_bytes\":"<<ledger.payload_bytes<<",\"metadata_bytes\":"<<ledger.metadata_bytes<<",\"frame_bytes\":"<<ledger.total_bytes<<",\"final_bits\":"<<ledger.final_bits()<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
