#include "walloc.hpp"
#include <ATen/Context.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace walloc;
int main(int argc,char** argv){try{
  if(argc!=4)throw std::runtime_error("FRAME OUTPUT MODE");Codec::configure_cpu_threads(1);
  std::string mode=argv[3];if(mode=="deterministic")at::globalContext().setDeterministicMkldnn(true);
  if(mode=="nomkldnn")at::globalContext().setUserEnabledMkldnn(false);
  std::ifstream f(argv[1],std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("frame open");auto n=f.tellg();Bytes bytes(n);f.seekg(0);if(!f.read(reinterpret_cast<char*>(bytes.data()),n))throw std::runtime_error("frame read");
  auto y=Codec::decode(bytes);std::ofstream output(argv[2],std::ios::binary);output.write(reinterpret_cast<const char*>(y.values.data()),y.values.size()*4);if(!output)throw std::runtime_error("output");return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
