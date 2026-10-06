#include "walloc.hpp"
#include <algorithm>
#include <cmath>
#include <cfenv>
#include <cstring>
#include <future>
#include <iostream>
#include <limits>
#include <stdexcept>
#if defined(__x86_64__)
#include <xmmintrin.h>
#endif
using namespace walloc;
void check(bool b,const char* message){if(!b)throw std::runtime_error(message);}
template<class F>void rejects(F f){bool failed=false;try{f();}catch(const std::exception&){failed=true;}check(failed,"expected deterministic rejection");}
void checksum(Bytes& b){std::uint32_t x=~std::uint32_t(0);for(std::size_t i=0;i<b.size()-4;++i){x^=b[i];for(int j=0;j<8;++j)x=(x>>1)^(0xedb88320u&(~(x&1)+1));}x=~x;for(int i=0;i<4;++i)b[b.size()-4+i]=std::uint8_t(x>>(8*i));}
int main(){try{
  Codec::configure_cpu_threads(1);Config c;c.channels=2;c.levels=2;c.encoder_width=12;c.decoder_width=12;c.latent_dim=3;
  auto m=Codec::initialize(c,42);auto bytes=m->model();Codec imported(bytes);check(imported.model()==bytes,"neutral model roundtrip");
  std::vector<float> x(2*257);for(std::size_t i=0;i<x.size();++i)x[i]=.2f*std::sin(float(i)*.07f);auto copy=x;
  auto e=m->evaluate(x.data(),x.size(),1,257,true);check(e.stages.at("decoded").shape==std::vector<std::int64_t>({1,2,257}),"crop shape");check(x==copy,"input modified");
  auto rounding=std::fegetround();std::fesetround(FE_DOWNWARD);rejects([&]{m->evaluate(x.data(),x.size(),1,257,true);});check(std::fegetround()==FE_DOWNWARD,"rounding changed on rejection");std::fesetround(rounding);
#if defined(__x86_64__)
  unsigned csr=_mm_getcsr();_mm_setcsr(csr|0x8040u);rejects([&]{m->evaluate(x.data(),x.size(),1,257,true);});check(_mm_getcsr()==(csr|0x8040u),"FTZ/DAZ changed on rejection");_mm_setcsr(csr);
  m->evaluate(x.data(),x.size(),1,257,true);check(_mm_getcsr()==csr,"floating point state not preserved");
#endif
  auto frame=m->encode(x.data(),x.size(),257);Ledger ledger;auto y=Codec::decode(frame,"cpu",&ledger);check(y.values==e.stages.at("decoded").values,"fresh complete frame decode");check(ledger.total_bytes*8==ledger.final_bits()&&ledger.model_bytes+ledger.payload_bytes+ledger.metadata_bytes==frame.size(),"ledger closure");
  Encoder encoder(*m);rejects([&]{encoder.bound();});encoder.compress(x.data(),x.size(),257);auto n=encoder.bound();Bytes out(n+2,0xa5);check(encoder.finalize(out.data()+1,n-1)==n,"bound-1 query");check(std::all_of(out.begin(),out.end(),[](auto b){return b==0xa5;}),"bound-1 writes");encoder.finalize(out.data()+1,n);check(out[0]==0xa5&&out.back()==0xa5,"canary");check(Bytes(out.begin()+1,out.end()-1)==frame,"finalize output");auto first=out;encoder.finalize(out.data()+1,n);check(out==first,"repeat finalize");encoder.reset();rejects([&]{encoder.finalize(nullptr,0);});
  for(std::size_t L:{0,1,2,255,256,257,65535,65536,65537}){std::vector<float> v(c.channels*L);auto b=m->encode(v.data(),v.size(),L);auto d=Codec::decode(b);check(d.values.size()==v.size(),"pipeline length boundary");}
  // Every truncation for small model; every header/payload boundary on complete frame.
  for(std::size_t i=0;i<bytes.size();++i){Bytes b(bytes.begin(),bytes.begin()+i);rejects([&]{Codec invalid(b);});}
  for(std::size_t i:{0,1,8,12,16,55,56,57,59}){Bytes b(frame.begin(),frame.begin()+i);rejects([&]{Codec::decode(b);});}
  for(std::size_t i=0;i<frame.size();i+=std::max<std::size_t>(1,frame.size()/500)){auto b=frame;b[i]^=0x80;rejects([&]{Codec::decode(b);});}
  for(std::size_t i:{8,12,16,24,32,40,48}){auto b=frame;if(i==16)std::fill(b.begin()+16,b.begin()+24,0xff);else b[i]^=0x80;checksum(b);rejects([&]{Codec::decode(b);});}
  for(std::size_t i=56+bytes.size();i<frame.size()-4;++i){auto b=frame;b[i]^=0x80;checksum(b);bool decoded=false;Tensor d;try{d=Codec::decode(b);decoded=true;}catch(const std::exception&){}if(decoded)check(std::all_of(d.values.begin(),d.values.end(),[](float f){return std::isfinite(f);}),"fuzz nonfinite reconstruction");}
  auto bad=x;bad[0]=std::numeric_limits<float>::infinity();rejects([&]{m->encode(bad.data(),bad.size(),257);});rejects([&]{Codec unavailable(bytes,"bad-device");});rejects([&]{m->evaluate(x.data(),x.size()-1,1,257);});
  Config oversized=c;oversized.channels=33;rejects([&]{Codec::initialize(oversized,0);});
  auto expected=m->encode(x.data(),x.size(),257);std::vector<std::future<Bytes>> concurrent;
  for(int i=0;i<4;++i)concurrent.push_back(std::async(std::launch::async,[&]{Codec handle(bytes);return handle.encode(x.data(),x.size(),257);}));for(auto& f:concurrent)check(f.get()==expected,"concurrent handles");
  std::vector<float> training(2*256);for(std::size_t i=0;i<training.size();++i)training[i]=.1f*std::cos(float(i)*.17f);
  TrainingOptions options;options.transform_weight=.25;
  auto a=Codec::initialize(c,1729);auto b=Codec::initialize(c,1729);check(a->model()==b->model(),"seed initialization");a->train(training.data(),training.size(),1,256,options,100);auto checkpoint=a->checkpoint();b->restore_checkpoint(checkpoint);check(b->model()==a->model(),"checkpoint model");
  a->train_continue(training.data(),training.size(),1,256,options);b->train_continue(training.data(),training.size(),1,256,options);check(a->model()==b->model()&&a->checkpoint()==b->checkpoint(),"optimizer and RNG resume");
  auto checkpoint_bad=checkpoint;checkpoint_bad.back()^=1;rejects([&]{b->restore_checkpoint(checkpoint_bad);});b->reset_optimizer();
  auto accum_a=Codec::initialize(c,37),accum_b=Codec::initialize(c,37);
  accum_a->train(training.data(),training.size(),1,256,options,81,false);accum_b->train(training.data(),training.size(),1,256,options,81,false);
  accum_b->restore_checkpoint(accum_a->checkpoint());accum_a->apply_accumulated(options);accum_b->apply_accumulated(options);check(accum_a->model()==accum_b->model(),"accumulated checkpoint resume");
  Config neural=c;neural.lightweight=false;neural.post_filter=false;auto alternate=Codec::initialize(neural,7);check(alternate->evaluate(training.data(),training.size(),1,256).stages.at("decoded").values.size()==training.size(),"alternate neural/no post");alternate->train(training.data(),training.size(),1,256,options,100);
  Tensor instruments{{2,4,512},std::vector<float>(2*4*512)};for(std::size_t i=0;i<instruments.values.size();++i)instruments.values[i]=float(i%37);auto mix=Codec::mix_crop(instruments,9,256,{1,0,.5f,1.5f});check(mix.shape==std::vector<std::int64_t>({2,256}),"mix layout");check(*std::max_element(mix.values.begin(),mix.values.end())<=.5f,"normalize range");
  Schedule schedule;check(schedule.observe(63,-2)>schedule.min_lr,"warmup");schedule.current_lr=3e-5;schedule.observe(5001,-2);for(int i=0;i<65;++i)schedule.observe(5001,-1);check(schedule.current_lr<3e-5,"plateau");
  std::cout<<"PASS: frames/lifecycle/bounds/canaries/model/frame rejection/real training/resume/alternate/concurrency\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
