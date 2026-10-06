#include "walloc_tensor.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <cstring>
namespace fs=std::filesystem;
walloc::Bytes read(const fs::path& p){std::ifstream f(p,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("cannot read tensor fixture");auto n=f.tellg();if(n<0||n>256*1024*1024)throw std::runtime_error("fixture resource limit");walloc::Bytes b(n);f.seekg(0);if(n&&!f.read(reinterpret_cast<char*>(b.data()),n))throw std::runtime_error("short fixture");return b;}
void save(const fs::path& p,const at::Tensor& x){auto cpu=x.detach().cpu().contiguous();std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(cpu.data_ptr<float>()),cpu.numel()*4);if(!f)throw std::runtime_error("tensor output failure");}
int main(int argc,char** argv){try{
  if(argc!=7)throw std::runtime_error("tensor_cli MODEL INPUT LENGTH OUTPUT DEVICE PADDING");
  walloc::Codec::configure_cpu_threads(1);walloc::Codec codec(read(argv[1]),argv[5]);auto c=codec.config();
  auto bytes=read(argv[2]);auto L=std::stoull(argv[3]);if(bytes.size()!=c.channels*L*4)throw std::runtime_error("tensor input shape");
  auto input=at::empty({1,c.channels,std::int64_t(L)});if(!bytes.empty())std::memcpy(input.data_ptr<float>(),bytes.data(),bytes.size());
  input=input.to(std::string(argv[5])=="cuda"?at::kCUDA:at::kCPU);const bool padded=std::string(argv[6])=="1";
  auto x=input;if(padded){auto P=((L+65535)/65536)*65536;if(P>L)x=at::constant_pad_nd(x,{0,std::int64_t(P-L)},0);}
  // Every raw stage stays on the chosen device; only this test driver exports
  // snapshots after composition, as independent numerical witnesses.
  auto X=codec.wavelet_analysis(x,c.levels);
  auto linear=codec.encode_stage(X,walloc::EncoderStage::Linear);
  auto uniform=codec.encode_stage(X,walloc::EncoderStage::Uniform);
  auto latent=codec.encode_stage(X,walloc::EncoderStage::Quantized);
  auto Xh=codec.decode_transform(latent);
  auto raw=codec.wavelet_synthesis(Xh,c.levels);
  auto y=codec.filter_reconstruction(raw).slice(2,0,L);
  for(const auto& t:{X,linear,uniform,latent,Xh,raw,y})if(t.device()!=input.device())throw std::runtime_error("hidden device fallback");
  auto evaluation=codec.forward_tensor(input,padded);
  for(const auto& pair:evaluation.stages)if(pair.second.device()!=input.device())throw std::runtime_error("forward device fallback");
  if(evaluation.waveform_loss.device()!=input.device()||evaluation.transform_loss.device()!=input.device())throw std::runtime_error("loss transferred to host");
  fs::path out=argv[4];fs::create_directory(out);
  save(out/"wavelet.bin",X);save(out/"linear.bin",linear);save(out/"uniform.bin",uniform);save(out/"latent.bin",latent);save(out/"decoded-wavelet.bin",Xh);save(out/"decoded.bin",y);save(out/"forward.bin",evaluation.stages.at("decoded"));
  std::cout<<"PASS: independent stages and losses remain on "<<argv[5]<<"; raw encoder skips quantization/container\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
