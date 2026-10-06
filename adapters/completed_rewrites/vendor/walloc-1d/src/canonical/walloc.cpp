// Translated WaLLoC Codec1D graph and complete frame. ATen is a native primitive
// dependency; this code does not load, interpret or invoke an upstream program.
// Oobleck graph semantics: HuggingFace diffusers 0.30.3, Apache-2.0 (LICENSES).
// AFB/SFB custom backward: pytorch_wavelets 1.3.0, BSD-3-Clause (LICENSES).
#include "walloc_tensor.hpp"
#include <ATen/ATen.h>
#include <ATen/Context.h>
#include <ATen/Parallel.h>
#include <ATen/CPUGeneratorImpl.h>
#include <torch/csrc/autograd/custom_function.h>
#include <torch/csrc/autograd/grad_mode.h>
#include <webp/decode.h>
#include <webp/encode.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cfenv>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <utility>
#if defined(__x86_64__)
#include <xmmintrin.h>
#endif

namespace walloc {
at::Tensor safe_broadcast_sum(const at::Tensor&);
namespace {
using T=at::Tensor;
constexpr std::size_t MiB=1024*1024, model_limit=256*MiB,frame_limit=512*MiB;
constexpr std::uint64_t tensor_limit=64*1024*1024;
std::mutex rng_mutex;
std::mutex cuda_mutex;
void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
struct FpGuard {
  std::fenv_t saved{};
#if defined(__x86_64__)
  unsigned csr=0;
#endif
  FpGuard(){
    require(std::fegetenv(&saved)==0&&std::fegetround()==FE_TONEAREST,"unsupported floating point rounding profile");
#if defined(__x86_64__)
    csr=_mm_getcsr();require((csr&0x8040u)==0&&(csr&0x1f80u)==0x1f80u,"unsupported FTZ/DAZ/exception-mask profile");
#endif
  }
  ~FpGuard(){std::fesetenv(&saved);
#if defined(__x86_64__)
    _mm_setcsr(csr);
#endif
  }
};
std::uint64_t product(const std::vector<std::int64_t>& shape){
  std::uint64_t n=1;require(!shape.empty()&&shape.size()<=4,"invalid rank");
  for(auto d:shape){require(d>=0&&static_cast<std::uint64_t>(d)<=tensor_limit,"invalid dimension");
    if(!d){n=0;continue;}require(n<=tensor_limit/static_cast<std::uint64_t>(d),"tensor resource limit");n*=d;}
  return n;
}
void put(Bytes& b,std::uint64_t x,unsigned n){for(unsigned i=0;i<n;++i)b.push_back(static_cast<std::uint8_t>(x>>(8*i)));}
struct Reader {
  const Bytes& b;std::size_t p=0;
  void need(std::size_t n)const{require(n<=b.size()-p,"truncated input");}
  std::uint64_t get(unsigned n){need(n);std::uint64_t x=0;for(unsigned i=0;i<n;++i)x|=std::uint64_t(b[p++])<<(8*i);return x;}
  std::string text(std::size_t n){need(n);std::string s(reinterpret_cast<const char*>(b.data()+p),n);p+=n;return s;}
  Bytes take(std::size_t n){need(n);Bytes x(b.begin()+static_cast<std::ptrdiff_t>(p),b.begin()+static_cast<std::ptrdiff_t>(p+n));p+=n;return x;}
};
std::uint32_t crc(const std::uint8_t* p,std::size_t n){
  std::uint32_t x=~std::uint32_t(0);for(std::size_t i=0;i<n;++i){x^=p[i];for(int j=0;j<8;++j)x=(x>>1)^(0xedb88320u&(~(x&1)+1));}return ~x;
}
T from_tensor(const Tensor& x,const at::Device& d){
  require(product(x.shape)==x.values.size(),"tensor size mismatch");
  T t=at::empty(x.shape,at::TensorOptions().dtype(at::kFloat));
  if(!x.values.empty())std::memcpy(t.data_ptr<float>(),x.values.data(),x.values.size()*4);
  return t.to(d);
}
Tensor snapshot(const T& x){
  T t=x.detach().to(at::kCPU).contiguous();Tensor o;
  o.shape=t.sizes().vec();const auto n=t.numel();require(n>=0&&std::uint64_t(n)<=tensor_limit,"snapshot resource limit");
  o.values.resize(static_cast<std::size_t>(n));if(n)std::memcpy(o.values.data(),t.data_ptr<float>(),static_cast<std::size_t>(n)*4);return o;
}
at::Device device(const std::string& name){
  require(name=="cpu"||name=="cuda","unsupported device");
  if(name=="cuda")require(at::hasCUDA()&&at::getNumGPUs()>0,"CUDA unavailable; no CPU fallback");
  return at::Device(name=="cpu"?at::kCPU:at::kCUDA, name=="cpu"?-1:0);
}
void config_valid(const Config& c){
  require(c.channels>=1&&c.channels<=32&&c.levels<=10&&c.latent_dim>=1&&c.latent_dim<=1024,"invalid configuration");
  require(c.latent_bits>=2&&c.latent_bits<=8&&c.decoder_width>=c.latent_dim&&c.decoder_width<=2048,"invalid decoder width/bits");
  require(c.lightweight||(c.encoder_width>=c.latent_dim&&c.encoder_width<=2048),"invalid encoder width");
  require(std::uint64_t(c.channels)*(1u<<c.levels)<=32768,"wavelet channel resource limit");
}
void restore_rng(const Bytes& bytes,const at::Device& d){
  require(!bytes.empty()&&bytes.size()<=1024*1024,"invalid RNG state");
  T t=at::empty({std::int64_t(bytes.size())},at::TensorOptions().dtype(at::kByte));
  std::memcpy(t.data_ptr<std::uint8_t>(),bytes.data(),bytes.size());
  auto generator=at::globalContext().defaultGenerator(d);generator.set_state(t);
}
void put_config(Bytes& b,const Config& c){for(auto x:{c.channels,c.levels,c.encoder_width,c.decoder_width,c.latent_dim,c.latent_bits,std::uint32_t(c.lightweight),std::uint32_t(c.post_filter)})put(b,x,4);}
Config get_config(Reader& r){
  Config c;c.channels=r.get(4);c.levels=r.get(4);c.encoder_width=r.get(4);c.decoder_width=r.get(4);c.latent_dim=r.get(4);c.latent_bits=r.get(4);
  auto l=r.get(4),p=r.get(4);require(l<=1&&p<=1,"invalid bool");c.lightweight=l;c.post_filter=p;config_valid(c);return c;
}
// The source uses a single wrap slice, even for unusually short wavelet lengths.
T source_roll(const T& x,std::int64_t n){
  const auto len=x.size(-1);require(len>0,"empty wavelet input");if(n<0)n=len+n;
  if(n==0)return x;
  auto cut=-n;if(cut<0)cut+=len;cut=std::clamp<std::int64_t>(cut,0,len);
  return at::cat({x.slice(-1,cut,len),x.slice(-1,0,cut)},-1);
}
T analysis_raw(T x,const T& h0,const T& h1){
  const auto C=x.size(1),K=h0.numel();auto N=x.size(2);
  require(N>0,"empty wavelet input");if(N%2){x=at::cat({x,x.slice(2,N-1,N)},2);++N;}
  x=source_roll(x,-K/2);
  auto h=at::cat({h0.reshape({1,1,1,K}),h1.reshape({1,1,1,K})},0).repeat({C,1,1,1});
  T y=at::conv2d(x.unsqueeze(2),h,{}, {1,2},at::IntArrayRef({0,K-1}),{1,1},C).squeeze(2);
  const auto L=N/2,fold=K/2;
  // Source broadcasting is kept for short valid domains; incompatible slices fail.
  y.slice(2,0,fold).copy_(y.slice(2,0,fold)+y.slice(2,L,L+fold));return y.slice(2,0,L);
}
T synthesis_raw(const T& packed,const T& g0,const T& g1){
  const auto C=packed.size(1)/2,L=packed.size(2),K=g0.numel(),N=2*L;
  require(C>0&&packed.size(1)%2==0&&L>0,"invalid synthesis shape");
  T bands=packed.reshape({packed.size(0),C,2,L});
  T lo=bands.select(2,0).unsqueeze(2),hi=bands.select(2,1).unsqueeze(2);
  T a=g0.reshape({1,1,1,K}).repeat({C,1,1,1}),b=g1.reshape({1,1,1,K}).repeat({C,1,1,1});
  T y=at::conv_transpose2d(lo,a,{}, {1,2},{0,0},{0,0},C,{1,1})+
      at::conv_transpose2d(hi,b,{}, {1,2},{0,0},{0,0},C,{1,1});
  y=y.squeeze(2);y.slice(2,0,K-2).copy_(y.slice(2,0,K-2)+y.slice(2,N,N+K-2));
  return source_roll(y.slice(2,0,N),1-K/2);
}
class Analysis:public torch::autograd::Function<Analysis>{
 public:
  static T forward(torch::autograd::AutogradContext* ctx,T x,T h0,T h1){
    ctx->save_for_backward({h0,h1});ctx->saved_data["length"]=x.size(2);return analysis_raw(x,h0,h1);
  }
  static torch::autograd::variable_list backward(torch::autograd::AutogradContext* ctx,torch::autograd::variable_list grad){
    auto h=ctx->get_saved_variables();T dx=synthesis_raw(grad.at(0),h[0],h[1]);
    dx=dx.slice(2,0,ctx->saved_data["length"].toInt());return {dx,T(),T()};
  }
};
class Synthesis:public torch::autograd::Function<Synthesis>{
 public:
  static T forward(torch::autograd::AutogradContext* ctx,T x,T g0,T g1){ctx->save_for_backward({g0,g1});return synthesis_raw(x,g0,g1);}
  static torch::autograd::variable_list backward(torch::autograd::AutogradContext* ctx,torch::autograd::variable_list grad){auto g=ctx->get_saved_variables();return {analysis_raw(grad.at(0),g[0],g[1]),T(),T()};}
};
// Preserve implicit-broadcast arithmetic and gradient order. Only the CUDA
// broadcast gradient reduction uses a private, barrier-repaired native primitive.
// No ATen dispatcher/global dependency is modified.
class SafeBroadcast:public torch::autograd::Function<SafeBroadcast>{
 public:
  static T forward(torch::autograd::AutogradContext*,T parameter,T like){return parameter.expand(like.sizes());}
  static torch::autograd::variable_list backward(torch::autograd::AutogradContext*,torch::autograd::variable_list grad){return {safe_broadcast_sum(grad.at(0)),T()};}
};
struct Named {std::string name;T value;};
void tensor_put(Bytes& b,const std::string& name,const T& value){
  T x=value.detach().to(at::kCPU).contiguous();require(name.size()<=256,"model key limit");
  put(b,name.size(),4);b.insert(b.end(),name.begin(),name.end());put(b,x.dim(),4);
  for(auto d:x.sizes())put(b,d,8);
  put(b,x.numel()*4,8);
  const auto* p=reinterpret_cast<const std::uint8_t*>(x.data_ptr<float>());b.insert(b.end(),p,p+x.numel()*4);
  require(b.size()<=model_limit,"model resource limit");
}
Named tensor_get(Reader& r,const at::Device& d){
  auto n=r.get(4);require(n>0&&n<=256,"invalid model key");auto name=r.text(n);
  require(name.find('\0')==std::string::npos,"invalid model key");auto rank=r.get(4);require(rank>=1&&rank<=4,"invalid tensor rank");
  std::vector<std::int64_t> shape;for(std::uint64_t i=0;i<rank;++i){auto k=r.get(8);require(k>0&&k<=tensor_limit,"invalid model dimension");shape.push_back(k);}
  auto count=product(shape),bytes=r.get(8);require(count*4==bytes,"model payload size mismatch");r.need(bytes);
  T x=at::empty(shape,at::TensorOptions().dtype(at::kFloat));std::memcpy(x.data_ptr<float>(),r.b.data()+r.p,bytes);r.p+=bytes;
  require(at::isfinite(x).all().item<bool>(),"nonfinite model");return {name,x.to(d)};
}
} // namespace

struct Codec::Impl {
  Config c;at::Device dev;std::vector<Named> state;std::map<std::string,std::size_t> lookup;
  std::vector<std::string> params;std::map<std::string,T> moment1,moment2,accum;
  std::uint64_t updates=0;Bytes cpu_rng,device_rng;mutable std::mutex mutex;
  explicit Impl(Config cc,at::Device dd):c(cc),dev(dd){config_valid(c);}
  T get(const std::string& key)const{auto i=lookup.find(key);require(i!=lookup.end(),"missing model key");return state.at(i->second).value;}
  void add(std::string n,T x,bool parameter){
    require(!lookup.count(n),"duplicate model key");lookup[n]=state.size();
    x=x.detach().clone().to(dev);x.set_requires_grad(parameter);state.push_back({n,x});if(parameter)params.push_back(n);
  }
  void conv_init(const std::string& n,std::int64_t in,std::int64_t out,std::int64_t k,bool norm=false,bool transpose=false,bool bias=true,bool random=true){
    const auto elements=product({in,out,k});
    std::uint64_t used=0;for(const auto& v:state)used+=std::uint64_t(v.value.numel())*4;
    require(elements*4+std::uint64_t(out+in)*8<=model_limit-used,"model allocation resource limit");
    auto o=at::TensorOptions().dtype(at::kFloat).device(at::kCPU);
    T w=at::empty({transpose?in:out,transpose?out:in,k},o);
    if(random){const double bound=1/std::sqrt(double((transpose?out:in)*k));w.uniform_(-bound,bound);}else w.zero_();
    if(bias){T b=at::empty({out},o);if(random){const double bound=1/std::sqrt(double((transpose?out:in)*k));b.uniform_(-bound,bound);}else b.zero_();
      // Source state_dict order places bias before g/v on a weight-normalized conv.
      if(!norm)add(n+".weight",w,true);
      add(n+".bias",b,true);
    }else if(!norm)add(n+".weight",w,true);
    if(norm){add(n+".weight_g",at::norm_except_dim(w,2,0),true);add(n+".weight_v",w,true);}
  }
  void snake_init(const std::string& n,std::int64_t channels){
    add(n+".alpha",at::zeros({1,channels,1}),true);add(n+".beta",at::zeros({1,channels,1}),true);
  }
  void residual_init(const std::string& n,std::int64_t channels,bool random){
    snake_init(n+".snake1",channels);conv_init(n+".conv1",channels,channels,7,true,false,true,random);
    snake_init(n+".snake2",channels);conv_init(n+".conv2",channels,channels,1,true,false,true,random);
  }
  void graph_init(bool random){
    // Frozen source float32 bior4.4 filters; not a hidden external dictionary.
    const std::array<double,10> hlo={0, .03782845550726404,-.023849465019556843,-.11062440441843718,.37740285561283066,.8526986790088938,.37740285561283066,-.11062440441843718,-.023849465019556843,.03782845550726404};
    const std::array<double,10> hhi={-0.,-.06453888262869706,.04068941760916406,.41809227322161724,-.7884856164055829,.41809227322161724,.04068941760916406,-.06453888262869706,-0.,0};
    const std::array<double,10> glo={0,-.06453888262869706,-.04068941760916406,.41809227322161724,.7884856164055829,.41809227322161724,-.04068941760916406,-.06453888262869706,0,0};
    const std::array<double,10> ghi={0,-.03782845550726404,-.023849465019556843,.11062440441843718,.37740285561283066,-.8526986790088938,.37740285561283066,.11062440441843718,-.023849465019556843,-.03782845550726404};
    auto filter=[&](const std::array<double,10>& a,bool reverse){T t=at::empty({1,1,10});for(int i=0;i<10;++i)t.data_ptr<float>()[i]=static_cast<float>(a[reverse?9-i:i]);return t;};
    add("wt.h0",filter(hlo,true),false);add("wt.h1",filter(hhi,true),false);
    add("iwt.g0",filter(glo,false),false);add("iwt.g1",filter(ghi,false),false);
    const auto bands=std::int64_t(c.channels)*(1u<<c.levels),D=std::int64_t(c.latent_dim);
    if(c.lightweight)conv_init("encoder.0",bands,D,1,false,false,true,random);
    else {
      const auto H=D*(c.encoder_width/c.latent_dim);const std::string p="encoder.0";
      conv_init(p+".conv1",bands,D,7,true,false,true,random);
      for(int block=0;block<2;++block){auto in=block?H:D;auto n=p+".block."+std::to_string(block);
        for(int r=1;r<=3;++r)residual_init(n+".res_unit"+std::to_string(r),in,random);
        snake_init(n+".snake1",in);conv_init(n+".conv1",in,H,2,true,false,true,random);
      }snake_init(p+".snake1",H);conv_init(p+".conv2",H,D,3,true,false,true,random);
    }
    const auto H=D*(c.decoder_width/c.latent_dim);const std::string p="decoder.1";
    conv_init(p+".conv1",D,H,7,true,false,true,random);
    for(int block=0;block<2;++block){auto out=block?D:H;auto n=p+".block."+std::to_string(block);
      snake_init(n+".snake1",H);conv_init(n+".conv_t1",H,out,2,true,true,true,random);
      for(int r=1;r<=3;++r)residual_init(n+".res_unit"+std::to_string(r),out,random);
    }snake_init(p+".snake1",D);conv_init(p+".conv2",D,bands,7,true,false,false,random);
    if(c.post_filter)conv_init("post",c.channels,c.channels,129,false,false,true,random);
    std::uint64_t bytes=0;for(const auto& x:state)bytes+=x.value.numel()*4;
    require(bytes<=model_limit,"model resource limit");
  }
  T conv(const std::string& n,const T& x,std::int64_t pad,std::int64_t dilation=1,bool transpose=false)const{
    T w;if(lookup.count(n+".weight_v"))w=at::_weight_norm(get(n+".weight_v"),get(n+".weight_g"),0);else w=get(n+".weight");
    T b=lookup.count(n+".bias")?get(n+".bias"):T();
    // The CUDA convolution backward also uses the unpatched ATen sum for
    // bias gradients (notably post-filter B=1,C=2,L=65536). Its forward bias
    // is an unfused broadcast add; preserve that arithmetic while routing
    // only this broadcast's gradient through the private safe reduction.
    if(b.defined()&&dev.is_cuda()&&at::GradMode::is_enabled()){
      T y=transpose?at::conv_transpose1d(x,w,{}, {1},{pad},{0},1,{dilation}):at::conv1d(x,w,{}, {1},{pad},{dilation},1);
      return y+SafeBroadcast::apply(b.view({1,-1,1}),y);
    }
    return transpose?at::conv_transpose1d(x,w,b,{1},{pad},{0},1,{dilation}):at::conv1d(x,w,b,{1},{pad},{dilation},1);
  }
  T snake(const std::string& n,const T& x)const{
    T a=at::exp(get(n+".alpha")),b=at::exp(get(n+".beta"));
    if(dev.is_cuda()&&at::GradMode::is_enabled()){
      a=SafeBroadcast::apply(a,x);T inverse=SafeBroadcast::apply((b+1e-9).reciprocal(),x);
      return x+inverse*at::sin(a*x).pow(2);
    }
    return x+(b+1e-9).reciprocal()*at::sin(a*x).pow(2);
  }
  T residual(const std::string& n,const T& x,std::int64_t dilation)const{
    T y=conv(n+".conv1",snake(n+".snake1",x),3*dilation,dilation);
    y=conv(n+".conv2",snake(n+".snake2",y),0);return x+y;
  }
  T neural(const std::string& p,T x,bool decoder)const{
    x=conv(p+".conv1",x,3);
    for(int block=0;block<2;++block){auto n=p+".block."+std::to_string(block);
      if(decoder)x=conv(n+".conv_t1",snake(n+".snake1",x),1,1,true);
      for(int r=1;r<=3;++r)x=residual(n+".res_unit"+std::to_string(r),x,r==1?1:r==2?3:9);
      if(!decoder)x=conv(n+".conv1",snake(n+".snake1",x),1);
    }return conv(p+".conv2",snake(p+".snake1",x),decoder?3:1);
  }
  T analysis(T x)const{for(unsigned i=0;i<c.levels;++i)x=Analysis::apply(x,get("wt.h0"),get("wt.h1"));return x;}
  T synthesis(T x)const{for(unsigned i=0;i<c.levels;++i)x=Synthesis::apply(x,get("iwt.g0"),get("iwt.g1"));return x;}
  double scale()const{return (std::pow(2.,c.latent_bits-1)-1)/1.85;}
  double maximum()const{return std::pow(2.,c.latent_bits-1)-1+.5-1e-3;}
  T uniform(const T& x)const{
    T z=x/scale();T cdf=.5*(1+at::erf(z/std::sqrt(2.)));return 2*maximum()*(cdf-.5);
  }
  T normal(const T& z)const{T p=at::hardtanh(z/(2*maximum())+.5,.0001,.9999);return scale()*(at::erfinv(2*p-1)*std::sqrt(2.));}
  T decode_raw(const T& z)const{
    T x=synthesis(neural("decoder.1",normal(z),true));if(c.post_filter)x=conv("post",x,64);return x;
  }
  T input(const float* p,std::size_t count,std::size_t B,std::size_t L)const{
    require(B>0&&B<=32&&L<=tensor_limit&&count==product({std::int64_t(B),std::int64_t(c.channels),std::int64_t(L)}),"input size mismatch");
    require(p||count==0,"null input");T x=at::empty({std::int64_t(B),std::int64_t(c.channels),std::int64_t(L)});
    if(count)std::memcpy(x.data_ptr<float>(),p,count*4);
    require(at::isfinite(x).all().item<bool>(),"nonfinite signal");return x.to(dev);
  }
  std::map<std::string,T> forward(T x,bool train,bool padded)const{
    if(padded){const auto L=x.size(2),P=((L+65535)/65536)*65536;
      require(P>0&&std::uint64_t(P)<=tensor_limit,"padded resource limit");product({x.size(0),x.size(1),P});
      if(P>L)x=at::constant_pad_nd(x,{0,P-L},0);}
    T X=analysis(x),z0=c.lightweight?conv("encoder.0",X,1):neural("encoder.0",X,false);
    T u=uniform(z0),z=train?u+(at::rand_like(u)-.5):at::round(u),Xh=neural("decoder.1",normal(z),true),y=synthesis(Xh);
    if(c.post_filter)y=conv("post",y,64);
    return {{"wavelet",X},{"linear",z0},{"uniform",u},{"latent",z},{"decoded-wavelet",Xh},{"raw-decoded",y},{"decoded",at::hardtanh(y,-.5,.5)}};
  }
  Evaluation evaluation(const std::map<std::string,T>& m,const T& x,bool padded)const{
    Evaluation e;for(const auto& kv:m){T t=kv.second;if(padded&&(kv.first=="decoded"||kv.first=="raw-decoded"))t=t.slice(2,0,x.size(2));e.stages.emplace(kv.first,snapshot(t));}
    T y=m.at("raw-decoded");if(padded)y=y.slice(2,0,x.size(2));
    e.waveform_loss=at::mse_loss(y,x).item<float>();e.transform_loss=at::mse_loss(m.at("wavelet"),m.at("decoded-wavelet")).item<float>();return e;
  }
  Bytes model_bytes()const{Bytes b={'W','L','M','O','D','0','0','1'};put_config(b,c);put(b,state.size(),4);for(const auto& n:state)tensor_put(b,n.name,n.value);return b;}
  void load_model(const Bytes& b){
    require(b.size()<=model_limit,"model resource limit");Reader r{b};require(r.text(8)=="WLMOD001","bad model magic");
    Config cc=get_config(r);require(cc.channels==c.channels&&cc.levels==c.levels&&cc.encoder_width==c.encoder_width&&cc.decoder_width==c.decoder_width&&cc.latent_dim==c.latent_dim&&cc.latent_bits==c.latent_bits&&cc.lightweight==c.lightweight&&cc.post_filter==c.post_filter,"model configuration mismatch");
    auto n=r.get(4);require(n==state.size(),"model key count mismatch");std::map<std::string,T> incoming;
    for(std::uint64_t i=0;i<n;++i){auto v=tensor_get(r,dev);require(lookup.count(v.name)&&!incoming.count(v.name),"unexpected/duplicate model key");require(v.value.sizes()==get(v.name).sizes(),"model shape mismatch");incoming.emplace(v.name,v.value);}
    require(r.p==b.size(),"trailing model bytes");
    for(const auto& n:params)if(n.find("weight_g")!=std::string::npos){const auto v=n.substr(0,n.size()-1)+"v";require(at::norm_except_dim(incoming.at(v),2,0).gt(0).all().item<bool>(),"zero weight_norm denominator");}
    // Validation is complete before committing borrowed model state.
    for(auto& v:state){T value=incoming.at(v.name).detach();value.set_requires_grad(v.value.requires_grad());v.value=value;}
  }
  void apply(const TrainingOptions& o,std::size_t divisor){
    require(divisor>0&&!accum.empty(),"no accumulated gradients");
    require(o.learning_rate>0&&std::isfinite(o.learning_rate)&&o.weight_decay>=0&&std::isfinite(o.weight_decay)&&o.beta1>0&&o.beta1<1&&o.beta2>0&&o.beta2<1&&o.epsilon>0&&std::isfinite(o.epsilon),"invalid optimizer options");
    require(updates<1000000000,"optimizer step limit");++updates;at::NoGradGuard guard;
    const double bc1=1-std::pow(o.beta1,double(updates)),bc2=1-std::pow(o.beta2,double(updates));
    for(const auto& n:params){T g=accum.at(n)/double(divisor),p=get(n);
      if(!moment1.count(n)){moment1[n]=at::zeros_like(p);moment2[n]=at::zeros_like(p);}
      T m=moment1.at(n),v=moment2.at(n);p.mul_(1-o.learning_rate*o.weight_decay);
      m.lerp_(g,1-o.beta1);v.mul_(o.beta2).addcmul_(g,g,1-o.beta2);
      T denom=v.sqrt()/std::sqrt(bc2);denom.add_(o.epsilon);p.addcdiv_(m,denom,-o.learning_rate/bc1);
      require(at::isfinite(p).all().item<bool>(),"nonfinite parameter update");
    }accum.clear();
  }
  TrainingResult train_impl(T x,const TrainingOptions& o,bool update){
    require(std::isfinite(o.transform_weight),"invalid transform loss weight");
    for(const auto& n:params)get(n).mutable_grad()=T();
    auto stages=forward(x,true,false);T td=at::mse_loss(stages.at("raw-decoded"),x),tf=at::mse_loss(stages.at("decoded-wavelet"),stages.at("wavelet"));
    T loss=td+o.transform_weight*tf;require(at::isfinite(loss).item<bool>(),"nonfinite training loss");loss.backward();
    TrainingResult result;result.evaluation=evaluation(stages,x,false);
    for(const auto& n:params){T g=get(n).grad();require(g.defined()&&at::isfinite(g).all().item<bool>(),"nonfinite gradient");result.gradients.emplace(n,snapshot(g));
      if(accum.count(n))accum[n].add_(g.detach());else accum[n]=g.detach().clone();}
    if(update)apply(o,1);
    result.updates=updates;
    auto rng=at::globalContext().defaultGenerator(at::Device(at::kCPU));T rs=rng.get_state();cpu_rng.resize(rs.numel());std::memcpy(cpu_rng.data(),rs.data_ptr<std::uint8_t>(),cpu_rng.size());
    if(dev.is_cuda()){auto gen=at::globalContext().defaultGenerator(dev);T r=gen.get_state().cpu();device_rng.resize(r.numel());std::memcpy(device_rng.data(),r.data_ptr<std::uint8_t>(),device_rng.size());}
    return result;
  }
  void admission(std::size_t B,std::size_t L,bool padded,bool train)const{
    require(L<=tensor_limit&&B>0&&B<=32,"signal resource limit");
    std::uint64_t P=padded?((std::uint64_t(L)+65535)/65536)*65536:L;
    const auto Z=(P+(1u<<c.levels)-1)/(1u<<c.levels)+2;
    const auto H=std::max(c.decoder_width,c.lightweight?0u:c.encoder_width);
    std::uint64_t model=0;for(const auto& n:state)model+=n.value.numel()*4;
    const auto estimate=4*std::uint64_t(B)*((train?20:10)*c.channels*P+(train?64:12)*H*Z+8*c.latent_dim*Z)+(train?5:2)*model;
    require(estimate<=(train?3ull:2ull)*1024*MiB,"working set admission limit");
  }
};

Codec::Codec(const Bytes& model,const std::string& d){
  FpGuard fp;
  require(model.size()<=model_limit,"model resource limit");Reader r{model};require(r.text(8)=="WLMOD001","bad model magic");Config c=get_config(r);
  // Validate framing before creating any tensor; truncated models cannot trigger
  // architecture allocations. Full key/shape/value validation follows below.
  const auto entries=r.get(4);require(entries>=4&&entries<=512,"model entry count limit");
  for(std::uint64_t i=0;i<entries;++i){auto key=r.get(4);require(key>0&&key<=256,"invalid model key");r.text(key);
    auto rank=r.get(4);require(rank>=1&&rank<=4,"invalid model rank");std::vector<std::int64_t> shape;
    for(std::uint64_t j=0;j<rank;++j){auto size=r.get(8);require(size>0&&size<=tensor_limit,"model dimension limit");shape.push_back(size);}
    auto bytes=r.get(8);require(bytes==4*product(shape),"model payload mismatch");r.need(bytes);r.p+=bytes;}
  require(r.p==model.size(),"model trailing bytes");
  auto dev=device(d);std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(dev.is_cuda())gpu.lock();
  p_=std::make_unique<Impl>(c,dev);p_->graph_init(false);p_->load_model(model);
}
Codec::Codec(std::unique_ptr<Impl> p):p_(std::move(p)){}
Codec::~Codec()=default;
std::unique_ptr<Codec> Codec::initialize(const Config& c,std::uint64_t seed,const std::string& d){
  FpGuard fp;
  auto dev=device(d);std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(rng_mutex);at::manual_seed(seed);auto p=std::make_unique<Impl>(c,dev);p->graph_init(true);return std::unique_ptr<Codec>(new Codec(std::move(p)));
}
Config Codec::config()const{return p_->c;}
namespace {
void tensor_domain(const T& x,const at::Device& d){
  require(x.defined()&&x.scalar_type()==at::kFloat&&x.device()==d&&x.dim()==3,"tensor dtype/device/rank mismatch");
  require(x.size(0)>0&&x.size(0)<=32&&x.size(1)>0&&x.size(2)>0,"empty tensor stage input");product(x.sizes().vec());
}
}
at::Tensor Codec::wavelet_analysis(const at::Tensor& x,unsigned levels){
  FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;tensor_domain(x,p_->dev);
  require(levels<=10&&std::uint64_t(x.size(1))*(1u<<levels)<=32768,"wavelet stage resource limit");
  T y=x;for(unsigned i=0;i<levels;++i)y=Analysis::apply(y,p_->get("wt.h0"),p_->get("wt.h1"));return y;
}
at::Tensor Codec::wavelet_synthesis(const at::Tensor& x,unsigned levels){
  FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;tensor_domain(x,p_->dev);
  require(levels<=10&&x.size(1)%(1u<<levels)==0&&std::uint64_t(x.size(2))<=tensor_limit/(1u<<levels),"invalid synthesis levels");
  T y=x;for(unsigned i=0;i<levels;++i)y=Synthesis::apply(y,p_->get("iwt.g0"),p_->get("iwt.g1"));return y;
}
at::Tensor Codec::encode_stage(const at::Tensor& x,EncoderStage stage){
  FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;tensor_domain(x,p_->dev);
  require(x.size(1)==std::int64_t(p_->c.channels)*(1u<<p_->c.levels),"encoder stage channels mismatch");
  require(std::uint64_t(x.size(2))<=tensor_limit/(1u<<p_->c.levels),"encoder stage resource limit");
  p_->admission(x.size(0),std::uint64_t(x.size(2))*(1u<<p_->c.levels),false,false);
  T z=p_->c.lightweight?p_->conv("encoder.0",x,1):p_->neural("encoder.0",x,false);
  if(stage==EncoderStage::Linear)return z;
  z=p_->uniform(z);
  if(stage==EncoderStage::Uniform)return z;
  require(stage==EncoderStage::Quantized,"unknown encoder stage");return at::round(z);
}
at::Tensor Codec::decode_transform(const at::Tensor& z){
  FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;tensor_domain(z,p_->dev);
  require(z.size(1)==p_->c.latent_dim&&z.size(2)>=3,"decoder stage shape mismatch");
  require(std::uint64_t(z.size(2)-2)<=tensor_limit/(1u<<p_->c.levels),"decoder stage resource limit");
  p_->admission(z.size(0),std::uint64_t(z.size(2)-2)*(1u<<p_->c.levels),false,false);
  return p_->neural("decoder.1",p_->normal(z),true);
}
at::Tensor Codec::filter_reconstruction(const at::Tensor& x,bool clamp){
  FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;tensor_domain(x,p_->dev);
  require(x.size(1)==p_->c.channels,"post-filter channel mismatch");p_->admission(x.size(0),x.size(2),false,false);
  T y=p_->c.post_filter?p_->conv("post",x,64):x;return clamp?at::hardtanh(y,-.5,.5):y;
}
TensorEvaluation Codec::forward_tensor(const at::Tensor& x,bool padded){
  FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;tensor_domain(x,p_->dev);
  require(x.size(1)==p_->c.channels,"forward tensor channel mismatch");p_->admission(x.size(0),x.size(2),padded,false);
  TensorEvaluation output;output.stages=p_->forward(x,false,padded);T y=output.stages.at("raw-decoded");
  if(padded){y=y.slice(2,0,x.size(2));output.stages["raw-decoded"]=y;output.stages["decoded"]=output.stages.at("decoded").slice(2,0,x.size(2));}
  output.waveform_loss=at::mse_loss(y,x);output.transform_loss=at::mse_loss(output.stages.at("wavelet"),output.stages.at("decoded-wavelet"));return output;
}
Bytes Codec::model()const{std::lock_guard<std::mutex> lock(p_->mutex);return p_->model_bytes();}
Evaluation Codec::evaluate(const float* in,std::size_t count,std::size_t B,std::size_t L,bool pad){
  FpGuard fp;
  std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;
  p_->admission(B,L,pad,false);
  T x=p_->input(in,count,B,L);auto stages=p_->forward(x,false,pad);return p_->evaluation(stages,x,pad);
}
Tensor Codec::decode_latent(const Tensor& latent,std::size_t L,bool crop){
  FpGuard fp;
  std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;
  require(latent.shape.size()==3&&latent.shape[0]>=1&&latent.shape[0]<=32&&latent.shape[1]==p_->c.latent_dim&&latent.shape[2]>=3,"latent shape mismatch");
  require(std::uint64_t(latent.shape[2]-2)<=tensor_limit/(1u<<p_->c.levels),"latent reconstruction resource limit");
  p_->admission(latent.shape[0],std::uint64_t(latent.shape[2]-2)*(1u<<p_->c.levels),false,false);
  T z=from_tensor(latent,p_->dev);require(at::isfinite(z).all().item<bool>(),"nonfinite latent");T y=p_->decode_raw(z);
  require(at::isfinite(y).all().item<bool>(),"nonfinite model reconstruction");
  if(crop){require(L<=std::size_t(y.size(2)),"crop length mismatch");y=y.slice(2,0,L);}return snapshot(at::hardtanh(y,-.5,.5));
}
Bytes Codec::latent_webp(const Tensor& z,unsigned bits){
  require(bits>=2&&bits<=8&&z.shape.size()==3&&z.shape[0]==1&&z.shape[1]>0&&z.shape[2]>0,"invalid latent container");
  require(product(z.shape)==z.values.size(),"latent size mismatch");const auto C=std::size_t(z.shape[1]),L=std::size_t(z.shape[2]);
  const auto n=std::size_t(std::sqrt(double(C/3)));require(C==3*n*n&&n>0,"RGB tiling needs latent_dim=3*n*n");
  const auto P=((L+127)/128)*128,W=128*n,H=(P/128)*n;require(W<=16383&&H<=16383&&W*H<=tensor_limit/3,"WebP dimension resource limit");
  std::vector<std::uint8_t> pixels(W*H*3,static_cast<std::uint8_t>(1u<<(bits-1)));
  const int offset=1<<(bits-1);
  for(std::size_t ch=0;ch<C;++ch)for(std::size_t i=0;i<L;++i){float v=z.values[ch*L+i];require(std::isfinite(v)&&v==std::nearbyint(v)&&v>=-offset&&v<offset,"invalid quantized latent");
    auto c=ch/(n*n),tile=ch%(n*n),row=(tile/n)*(P/128)+i/128,col=(tile%n)*128+i%128;
    pixels[(row*W+col)*3+c]=static_cast<std::uint8_t>(int(v)+offset);}
  WebPConfig config;require(WebPConfigInit(&config)!=0,"WebP configuration failure");config.lossless=1;config.quality=80;config.method=4;config.exact=0;config.thread_level=0;
  WebPPicture picture;require(WebPPictureInit(&picture)!=0,"WebP picture failure");picture.use_argb=1;picture.width=W;picture.height=H;
  WebPMemoryWriter writer;WebPMemoryWriterInit(&writer);picture.writer=WebPMemoryWrite;picture.custom_ptr=&writer;
  try {require(WebPPictureImportRGB(&picture,pixels.data(),W*3)!=0,"WebP allocation failure");require(WebPEncode(&config,&picture)!=0,"WebP encoding failure");
    require(writer.size<=frame_limit,"WebP payload resource limit");Bytes bytes(writer.mem,writer.mem+writer.size);WebPMemoryWriterClear(&writer);WebPPictureFree(&picture);return bytes;
  }catch(...){WebPMemoryWriterClear(&writer);WebPPictureFree(&picture);throw;}
}
Tensor Codec::webp_latent(const Bytes& bytes,unsigned C,unsigned bits,std::size_t L){
  require(bytes.size()<=frame_limit&&bits>=2&&bits<=8&&C>0&&C<=1024&&L>0&&L<=tensor_limit,"invalid WebP input");
  auto n=std::size_t(std::sqrt(double(C/3)));require(C==3*n*n&&n>0,"invalid RGB tiling");
  WebPBitstreamFeatures f;require(WebPGetFeatures(bytes.data(),bytes.size(),&f)==VP8_STATUS_OK&&!f.has_animation&&f.format==2&&!f.has_alpha,"not static lossless RGB WebP");
  auto P=((L+127)/128)*128,W=128*n,H=(P/128)*n;require(std::size_t(f.width)==W&&std::size_t(f.height)==H&&W*H<=tensor_limit/3,"WebP dimension mismatch");
  std::vector<std::uint8_t> pixels(W*H*3);require(WebPDecodeRGBInto(bytes.data(),bytes.size(),pixels.data(),pixels.size(),W*3)!=nullptr,"WebP decoding failure");
  Tensor z;z.shape={1,std::int64_t(C),std::int64_t(L)};z.values.resize(product(z.shape));const int offset=1<<(bits-1);
  for(std::size_t ch=0;ch<C;++ch)for(std::size_t i=0;i<P;++i){auto c=ch/(n*n),tile=ch%(n*n),row=(tile/n)*(P/128)+i/128,col=(tile%n)*128+i%128;
    int v=int(pixels[(row*W+col)*3+c])-offset;require(v>=-offset&&v<offset,"WebP value outside latent bit width");
    if(i<L)z.values[ch*L+i]=float(v);else require(v==0,"nonzero latent padding");}
  return z;
}
Bytes Codec::encode(const float* in,std::size_t count,std::size_t L,Ledger* ledger){
  FpGuard fp;
  std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::lock_guard<std::mutex> lock(p_->mutex);at::NoGradGuard guard;p_->admission(1,L,true,false);
  T x=p_->input(in,count,1,L);
  Bytes payload;std::size_t latent=0,padded=0;
  if(L){auto stages=p_->forward(x,false,true);auto z=snapshot(stages.at("latent"));latent=z.shape[2];padded=((L+65535)/65536)*65536;payload=latent_webp(z,p_->c.latent_bits);}
  Bytes m=p_->model_bytes(),b={'W','L','F','R','A','0','0','1'};put(b,1,4);put(b,p_->dev.is_cuda()?1:0,4);
  for(auto v:{std::uint64_t(L),std::uint64_t(padded),std::uint64_t(latent),std::uint64_t(m.size()),std::uint64_t(payload.size())})put(b,v,8);
  b.insert(b.end(),m.begin(),m.end());b.insert(b.end(),payload.begin(),payload.end());put(b,crc(b.data(),b.size()),4);
  require(b.size()<=frame_limit,"frame resource limit");if(ledger)*ledger={m.size(),payload.size(),60,b.size()};return b;
}
Tensor Codec::decode(const Bytes& b,const std::string& d,Ledger* ledger){
  require(b.size()>=60&&b.size()<=frame_limit,"invalid frame length");Reader tail{b};tail.p=b.size()-4;require(tail.get(4)==crc(b.data(),b.size()-4),"frame checksum mismatch");
  Reader r{b};require(r.text(8)=="WLFRA001"&&r.get(4)==1,"unknown frame version");auto profile=r.get(4);require(profile<=1,"unknown numerical profile");
  auto L=r.get(8),P=r.get(8),Z=r.get(8),M=r.get(8),S=r.get(8);require(M<=model_limit&&S<=frame_limit&&M<=b.size()-60&&S==b.size()-60-M,"frame size mismatch");
  Bytes m=r.take(M),s=r.take(S);Codec codec(m,d);auto c=codec.config();Tensor output;
  if(!L){require(!P&&!Z&&!S,"invalid empty frame");output.shape={1,std::int64_t(c.channels),0};}
  else {
    require(L<=tensor_limit&&P==((L+65535)/65536)*65536&&Z==P/(1u<<c.levels)+2,"inconsistent frame shape");
    product({1,std::int64_t(c.channels),std::int64_t(P)});Tensor latent=webp_latent(s,c.latent_dim,c.latent_bits,Z);output=codec.decode_latent(latent,L);
  }
  if(ledger)*ledger={std::size_t(M),std::size_t(S),60,b.size()};
  return output;
}
TrainingResult Codec::train(const float* in,std::size_t count,std::size_t B,std::size_t L,const TrainingOptions& o,std::uint64_t seed,bool update){
  FpGuard fp;
  std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::scoped_lock lock(rng_mutex,p_->mutex);p_->admission(B,L,false,true);at::manual_seed(seed);return p_->train_impl(p_->input(in,count,B,L),o,update);
}
TrainingResult Codec::train_replay(const float* in,std::size_t count,std::size_t B,std::size_t L,const TrainingOptions& o,const Bytes& cpu,const Bytes& gpu,bool update){
  FpGuard fp;
  std::unique_lock<std::mutex> gpu_lock(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu_lock.lock();
  std::scoped_lock lock(rng_mutex,p_->mutex);
  p_->admission(B,L,false,true);
  restore_rng(cpu,at::Device(at::kCPU));if(p_->dev.is_cuda())restore_rng(gpu,p_->dev);
  return p_->train_impl(p_->input(in,count,B,L),o,update);
}
TrainingResult Codec::train_continue(const float* in,std::size_t count,std::size_t B,std::size_t L,const TrainingOptions& o,bool update){
  FpGuard fp;
  std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();
  std::scoped_lock lock(rng_mutex,p_->mutex);p_->admission(B,L,false,true);
  restore_rng(p_->cpu_rng,at::Device(at::kCPU));if(p_->dev.is_cuda())restore_rng(p_->device_rng,p_->dev);
  return p_->train_impl(p_->input(in,count,B,L),o,update);
}
void Codec::apply_accumulated(const TrainingOptions& o,std::size_t divisor){FpGuard fp;std::unique_lock<std::mutex> gpu(cuda_mutex,std::defer_lock);if(p_->dev.is_cuda())gpu.lock();std::lock_guard<std::mutex> lock(p_->mutex);p_->apply(o,divisor);}
Bytes Codec::checkpoint()const{
  std::lock_guard<std::mutex> lock(p_->mutex);Bytes b={'W','L','T','R','N','0','0','1'},m=p_->model_bytes();put(b,m.size(),8);b.insert(b.end(),m.begin(),m.end());put(b,p_->updates,8);
  for(const auto* table:{&p_->moment1,&p_->moment2,&p_->accum}){put(b,table->size(),4);for(const auto& kv:*table)tensor_put(b,kv.first,kv.second);}
  for(const auto* rs:{&p_->cpu_rng,&p_->device_rng}){put(b,rs->size(),4);b.insert(b.end(),rs->begin(),rs->end());}
  put(b,crc(b.data(),b.size()),4);return b;
}
void Codec::restore_checkpoint(const Bytes& b){
  FpGuard fp;
  std::lock_guard<std::mutex> lock(p_->mutex);require(b.size()>=32&&b.size()<=frame_limit,"invalid checkpoint size");Reader tail{b};tail.p=b.size()-4;require(tail.get(4)==crc(b.data(),b.size()-4),"checkpoint checksum mismatch");
  Reader r{b};require(r.text(8)=="WLTRN001","bad training checkpoint");auto M=r.get(8);require(M<=model_limit,"checkpoint model limit");auto model=r.take(M);auto steps=r.get(8);require(steps<=1000000000,"optimizer step limit");
  std::array<std::map<std::string,T>,3> tables;
  for(auto& table:tables){auto N=r.get(4);require(N<=p_->params.size(),"optimizer key limit");
    for(std::uint64_t i=0;i<N;++i){auto v=tensor_get(r,p_->dev);require(std::find(p_->params.begin(),p_->params.end(),v.name)!=p_->params.end()&&!table.count(v.name),"bad optimizer key");require(v.value.sizes()==p_->get(v.name).sizes(),"optimizer shape mismatch");table.emplace(v.name,v.value);}
    require(N==0||N==p_->params.size(),"incomplete optimizer state");}
  require(tables[0].size()==tables[1].size()&&(!steps||tables[0].size()==p_->params.size()),"optimizer state mismatch");
  auto A=r.get(4);require(A<=1024*1024,"RNG state limit");auto cpu=r.take(A);auto B=r.get(4);require(B<=1024*1024,"RNG state limit");auto gpu=r.take(B);require(r.p==b.size()-4,"checkpoint trailing bytes");
  p_->load_model(model);p_->updates=steps;p_->moment1=std::move(tables[0]);p_->moment2=std::move(tables[1]);p_->accum=std::move(tables[2]);p_->cpu_rng=std::move(cpu);p_->device_rng=std::move(gpu);
}
void Codec::reset_optimizer(){std::lock_guard<std::mutex> lock(p_->mutex);p_->updates=0;p_->moment1.clear();p_->moment2.clear();p_->accum.clear();p_->cpu_rng.clear();p_->device_rng.clear();}
Tensor Codec::normalize(const Tensor& value){FpGuard fp;T x=from_tensor(value,at::Device(at::kCPU));require(x.numel()>0&&at::isfinite(x).all().item<bool>(),"invalid normalize input");x=x-x.mean();x=x/(x.abs().max()+1e-8);require(at::isfinite(x).all().item<bool>(),"normalization overflow");return snapshot(x/2);}
Tensor Codec::mix_crop(const Tensor& value,std::size_t start,std::size_t L,const std::vector<float>& w){
  FpGuard fp;
  require(value.shape.size()==3&&value.shape[1]==4&&w.size()==4&&L>0&&start<=std::size_t(value.shape[2])&&L<=std::size_t(value.shape[2])-start,"invalid mixture crop");
  for(float f:w)require(std::isfinite(f),"nonfinite mixing weights");
  T x=from_tensor(value,at::Device(at::kCPU));require(at::isfinite(x).all().item<bool>(),"nonfinite instruments");
  T weights=at::empty({1,4,1});std::memcpy(weights.data_ptr<float>(),w.data(),16);x=(x.slice(2,start,start+L)*weights).sum(1);return normalize(snapshot(x));
}
std::vector<std::vector<float>> Codec::mixing_weights(){
  std::vector<std::vector<float>> weights(1,std::vector<float>(4,1));
  for(int i=0;i<4;++i)for(int j=i+1;j<4;++j){std::vector<float> w(4,.5);w[i]=w[j]=1.5;weights.push_back(w);}
  for(int i=0;i<4;++i)for(int j=i+1;j<4;++j)for(int k=j+1;k<4;++k){std::vector<float> w(4,0);w[i]=w[j]=w[k]=1;weights.push_back(w);}
  for(int i=0;i<4;++i)for(int j=i+1;j<4;++j){std::vector<float> w(4,0);w[i]=w[j]=1;weights.push_back(w);}
  for(int i=0;i<4;++i){std::vector<float> w(4,0);w[i]=1;weights.push_back(w);}
  return weights;
}
bool Codec::cuda_available(){return at::hasCUDA()&&at::getNumGPUs()>0;}
void Codec::configure_cpu_threads(unsigned intra,unsigned inter){require(intra>=1&&intra<=32&&inter>=1&&inter<=32,"invalid thread count");std::lock_guard<std::mutex> lock(rng_mutex);at::set_num_threads(intra);at::set_num_interop_threads(inter);at::globalContext().setDeterministicMkldnn(true);at::globalContext().setBenchmarkCuDNN(false);at::globalContext().setDeterministicCuDNN(true);at::globalContext().setAllowTF32CuDNN(false);at::globalContext().setAllowTF32CuBLAS(false);}
Encoder::Encoder(Codec& c):codec_(c){}
void Encoder::compress(const float* input,std::size_t count,std::size_t length){require(!ready_,"reset before next object");frame_=codec_.encode(input,count,length);ready_=true;}
std::size_t Encoder::bound()const{require(ready_,"no encoded object");return frame_.size();}
std::size_t Encoder::finalize(std::uint8_t* p,std::size_t capacity)const{
  require(ready_,"no encoded object");
  if(capacity>=frame_.size()&&!frame_.empty()){
    if(!p)throw std::runtime_error("null output");
    std::memcpy(p,frame_.data(),frame_.size());
  }
  return frame_.size();
}
void Encoder::reset(){frame_.clear();ready_=false;}
double Schedule::observe(std::uint64_t step,double loss){
  require(min_lr>0&&max_lr>=min_lr&&factor>0&&factor<1&&plot_update>0&&warmup_steps/plot_update>0&&std::isfinite(loss),"invalid schedule");
  if(step<warmup_steps){++scheduler_step;const double scale=.5*(std::log10(max_lr)-std::log10(min_lr));const double angle=std::acos(-1.)*double(scheduler_step)/double(warmup_steps/plot_update);current_lr=std::pow(10.,std::log10(min_lr)+scale*(1-std::cos(angle)));}
  else {if(!has_best||loss<best*(1-threshold)){best=loss;has_best=true;bad_epochs=0;}else ++bad_epochs;
    if(bad_epochs>patience){auto next=std::max(min_lr,current_lr*factor);if(current_lr-next>1e-8)current_lr=next;bad_epochs=0;}}
  return current_lr;
}
} // namespace walloc
