#include "walloc.hpp"
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace fs=std::filesystem;
using walloc::Bytes;
Bytes read(const fs::path& p){
  std::ifstream f(p,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("cannot open input");
  auto n=f.tellg();if(n<0||n>512*1024*1024)throw std::runtime_error("input file limit");
  Bytes b(static_cast<std::size_t>(n));f.seekg(0);if(n&&!f.read(reinterpret_cast<char*>(b.data()),n))throw std::runtime_error("cannot read input");return b;
}
void write(const fs::path& p,const Bytes& b){std::ofstream f(p,std::ios::binary);if(!f)throw std::runtime_error("cannot open output");f.write(reinterpret_cast<const char*>(b.data()),b.size());if(!f)throw std::runtime_error("output failed");}
std::vector<float> floats(const fs::path& p){auto b=read(p);if(b.size()%4)throw std::runtime_error("partial float input");std::vector<float> x(b.size()/4);if(!b.empty())std::memcpy(x.data(),b.data(),b.size());return x;}
void tensor(const fs::path& folder,const std::string& name,const walloc::Tensor& x){
  Bytes b(x.values.size()*4);if(!b.empty())std::memcpy(b.data(),x.values.data(),b.size());write(folder/(name+".bin"),b);
  std::ofstream f(folder/(name+".shape"));for(auto d:x.shape)f<<d<<' ';f<<'\n';
}
void stages(const fs::path& folder,const walloc::Evaluation& e){
  fs::create_directory(folder);for(const auto& kv:e.stages)tensor(folder,kv.first,kv.second);
  std::ofstream f(folder/"losses.txt");f.precision(17);f<<e.waveform_loss<<' '<<e.transform_loss<<'\n';
}
std::size_t number(const char* text){std::size_t pos=0;std::string s=text;if(s.empty()||s[0]=='-')throw std::runtime_error("negative/empty number");auto n=std::stoull(s,&pos);if(pos!=s.size()||n>64*1024*1024)throw std::runtime_error("invalid/large number");return n;}
int main(int argc,char** argv){try {
  walloc::Codec::configure_cpu_threads(1);
  if(argc<2)throw std::runtime_error("commands: stage encode decode train init normalize mix webp-encode webp-decode");
  std::string command=argv[1];
  if(command=="stage"&&argc==9){auto model=read(argv[2]);auto x=floats(argv[3]);walloc::Codec codec(model,argv[7]);
    auto e=codec.evaluate(x.data(),x.size(),number(argv[4]),number(argv[5]),number(argv[8])!=0);stages(argv[6],e);return 0;}
  if(command=="encode"&&argc==7){walloc::Codec codec(read(argv[2]),argv[6]);auto x=floats(argv[3]);walloc::Ledger ledger;
    auto b=codec.encode(x.data(),x.size(),number(argv[4]),&ledger);write(argv[5],b);std::cout<<ledger.model_bytes<<' '<<ledger.payload_bytes<<' '<<ledger.metadata_bytes<<' '<<ledger.final_bits()<<'\n';return 0;}
  if(command=="decode"&&argc==5){auto x=walloc::Codec::decode(read(argv[2]),argv[4]);Bytes b(x.values.size()*4);if(!b.empty())std::memcpy(b.data(),x.values.data(),b.size());write(argv[3],b);return 0;}
  if(command=="init"&&argc==13){walloc::Config c;c.channels=number(argv[2]);c.levels=number(argv[3]);c.encoder_width=number(argv[4]);c.decoder_width=number(argv[5]);c.latent_dim=number(argv[6]);c.latent_bits=number(argv[7]);
    auto light=number(argv[8]),post=number(argv[9]);if(light>1||post>1)throw std::runtime_error("boolean must be 0 or 1");c.lightweight=light;c.post_filter=post;
    auto m=walloc::Codec::initialize(c,number(argv[10]),argv[12]);write(argv[11],m->model());return 0;}
  if(command=="train"&&(argc==9||argc==10)){walloc::Codec m(read(argv[2]),argv[7]);auto x=floats(argv[3]);auto B=number(argv[4]),L=number(argv[5]);fs::path out=argv[6],oracle=argv[8];fs::create_directory(out);
    walloc::TrainingOptions options;options.transform_weight=.25;
    auto steps=argc==10?number(argv[9]):3; if(steps<1||steps>100)throw std::runtime_error("training steps limit");
    for(std::size_t step=0;step<steps;++step){auto folder=out/("step-"+std::to_string(step));
      auto cpu=read(oracle/("rng-"+std::to_string(step)+".bin"));Bytes gpu;if(std::string(argv[7])=="cuda")gpu=read(oracle/("cuda-rng-"+std::to_string(step)+".bin"));
      auto result=m.train_replay(x.data(),x.size(),B,L,options,cpu,gpu);stages(folder,result.evaluation);
      fs::create_directory(folder/"gradients");std::ofstream names(folder/"gradients/names.txt");
      for(const auto& kv:result.gradients){tensor(folder/"gradients",kv.first,kv.second);names<<kv.first<<'\n';}
      write(folder/"updated.wlm",m.model());write(folder/"checkpoint.wlt",m.checkpoint());
    }return 0;}
  if(command=="webp-encode"&&argc==7){auto values=floats(argv[2]);walloc::Tensor z{{1,std::int64_t(number(argv[3])),std::int64_t(number(argv[4]))},std::move(values)};write(argv[5],walloc::Codec::latent_webp(z,number(argv[6])));return 0;}
  if(command=="webp-decode"&&argc==7){auto z=walloc::Codec::webp_latent(read(argv[2]),number(argv[3]),number(argv[6]),number(argv[4]));Bytes b(z.values.size()*4);if(!b.empty())std::memcpy(b.data(),z.values.data(),b.size());write(argv[5],b);return 0;}
  if(command=="latent-decode"&&argc==8){walloc::Codec m(read(argv[2]),argv[7]);auto v=floats(argv[3]);auto c=m.config();walloc::Tensor z{{1,c.latent_dim,std::int64_t(number(argv[4]))},std::move(v)};auto y=m.decode_latent(z,number(argv[5]));Bytes b(y.values.size()*4);if(!b.empty())std::memcpy(b.data(),y.values.data(),b.size());write(argv[6],b);return 0;}
  if(command=="qa"&&argc==3){fs::path out=argv[2];fs::create_directory(out);
    walloc::Tensor x{{2,4,512},std::vector<float>(4096)};for(std::size_t i=0;i<x.values.size();++i)x.values[i]=float(int(i%37)-18);
    tensor(out,"normalized",walloc::Codec::normalize(x));
    auto weights=walloc::Codec::mixing_weights();
    for(std::size_t i=0;i<weights.size();++i)tensor(out,"mix-"+std::to_string(i),walloc::Codec::mix_crop(x,9,256,weights[i]));
    walloc::Schedule s;std::ofstream f(out/"schedule.txt");f.precision(17);
    for(std::uint64_t i=0;i<80;++i)f<<s.observe(64*(i+1)-1,-2+double(i%3)*.001)<<'\n';
    for(std::uint64_t i=0;i<200;++i)f<<s.observe(6000,-1)<<'\n';return 0;}
  throw std::runtime_error("invalid command arguments");
}catch(const std::exception& e){std::cerr<<"walloc: "<<e.what()<<'\n';return 2;}}
