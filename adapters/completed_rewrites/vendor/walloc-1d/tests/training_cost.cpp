#include "walloc.hpp"
#include <ATen/detail/CUDAHooksInterface.h>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace walloc;
int main(int argc,char** argv){try{
  if(argc!=3)throw std::runtime_error("MODEL DEVICE");Codec::configure_cpu_threads(1);
  std::ifstream f(argv[1],std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("model open");auto size=f.tellg();if(size<=0||size>256*1024*1024)throw std::runtime_error("model size");Bytes model(size);f.seekg(0);if(!f.read(reinterpret_cast<char*>(model.data()),size))throw std::runtime_error("model read");
  std::string device=argv[2];constexpr std::size_t L=65536;std::vector<float> x(2*L);
  for(std::size_t i=0;i<L;++i){x[i]=.2f*std::sin(float(i)*.071f);x[L+i]=.17f*std::cos(float(i)*.037f);}
  auto sync=[&]{if(device=="cuda")at::detail::getCUDAHooks().deviceSynchronize(0);};TrainingOptions o;o.transform_weight=.25;
  std::cout.precision(17);std::cout<<"{\"seconds\":[";std::size_t params=0;
  for(int i=-1;i<2;++i){Codec c(model,device);sync();auto start=std::chrono::steady_clock::now();auto result=c.train(x.data(),x.size(),1,L,o,100);sync();auto end=std::chrono::steady_clock::now();
    if(i==0)for(const auto& kv:result.gradients)params+=kv.second.values.size();
    if(i>=0){if(i)std::cout<<',';std::cout<<std::chrono::duration<double>(end-start).count();}}
  std::cout<<"],\"parameters\":"<<params<<",\"batch\":1,\"length\":65536,\"updates_per_object\":1}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
