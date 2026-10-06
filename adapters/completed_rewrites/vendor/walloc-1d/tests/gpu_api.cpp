#include "walloc_tensor.hpp"
#include <ATen/detail/CUDAHooksInterface.h>
#include <cmath>
#include <future>
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace walloc;
void check(bool b,const char* m){if(!b)throw std::runtime_error(m);}
template<class F>void rejects(F f){bool failed=false;try{f();}catch(const std::exception&){failed=true;}check(failed,"expected device/dtype/shape rejection");}
int main(){try{
  Codec::configure_cpu_threads(1);check(Codec::cuda_available(),"CUDA required; no fallback");
  Config c;c.channels=2;c.levels=2;c.encoder_width=12;c.decoder_width=12;c.latent_dim=3;c.lightweight=false;
  auto m=Codec::initialize(c,19,"cuda");auto model=m->model();
  std::vector<float> x(512);for(std::size_t i=0;i<x.size();++i)x[i]=.2f*std::sin(float(i)*.03f);
  auto copy=x;auto expected=m->encode(x.data(),x.size(),256);auto y=Codec::decode(expected,"cuda");
  check(y.values==m->evaluate(x.data(),x.size(),1,256,true).stages.at("decoded").values,"GPU frame/fresh decode mismatch");
  auto t=at::from_blob(x.data(),{1,2,256},at::TensorOptions().dtype(at::kFloat)).clone().cuda();
  auto e=m->forward_tensor(t);check(e.waveform_loss.is_cuda()&&e.transform_loss.is_cuda(),"host loss fallback");
  for(const auto& kv:e.stages)check(kv.second.is_cuda()&&!kv.second.requires_grad(),"inference residency/autograd");
  rejects([&]{m->forward_tensor(t.cpu());});rejects([&]{m->forward_tensor(t.to(at::kDouble));});
  rejects([&]{m->encode_stage(t,EncoderStage::Linear);});rejects([&]{m->wavelet_synthesis(t,10);});
  std::vector<std::future<Bytes>> handles;
  for(int i=0;i<4;++i)handles.push_back(std::async(std::launch::async,[&]{Codec n(model,"cuda");return n.encode(x.data(),x.size(),256);}));
  for(auto& h:handles)check(h.get()==expected,"GPU independent handle mismatch");
  TrainingOptions o;o.transform_weight=.25;m->train(x.data(),x.size(),1,256,o,100);
  auto checkpoint=m->checkpoint();Codec restored(model,"cuda");restored.restore_checkpoint(checkpoint);
  m->train_continue(x.data(),x.size(),1,256,o);restored.train_continue(x.data(),x.size(),1,256,o);
  check(m->model()==restored.model()&&m->checkpoint()==restored.checkpoint(),"GPU RNG/optimizer resume mismatch");
  auto a=Codec::initialize(c,9,"cuda"),b=Codec::initialize(c,9,"cuda");
  a->train(x.data(),x.size(),1,256,o,81,false);b->restore_checkpoint(a->checkpoint());
  a->apply_accumulated(o);b->apply_accumulated(o);check(a->model()==b->model(),"GPU accumulated-gradient resume mismatch");
  check(copy==x,"borrowed input modified");at::detail::getCUDAHooks().deviceSynchronize(0);
  std::cout<<"PASS: explicit CUDA, device stages/losses, rejection, independent handles, frames, RNG/Adam/accumulation resume\n";
  return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
