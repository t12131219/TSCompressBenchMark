#include <ATen/ATen.h>
#include <ATen/Context.h>
#include <ATen/Parallel.h>
#include <ATen/detail/CUDAHooksInterface.h>
#include <iostream>
#include <stdexcept>
namespace walloc {at::Tensor safe_broadcast_sum(const at::Tensor&);}
int main(int argc,char** argv){try{
  const bool safety=argc==2&&std::string(argv[1])=="safety";at::set_num_threads(1);at::manual_seed(42);unsigned cases=0;
  for(int B:{1,2,32})for(int C:{3,12,27,108,756})for(int L:{1,32,256,258,260,512}){
    auto input=at::randn({B,C,L},at::TensorOptions().device(at::kCUDA));
    for(int strided=0;strided<2;++strided){auto x=strided?input.transpose(0,2):input;auto y=walloc::safe_broadcast_sum(x);
      if(!at::isfinite(y).all().item<bool>())throw std::runtime_error("nonfinite reduction");
      if(!safety&&!at::equal(y,at::sum(x,at::IntArrayRef({0,2}),true)))throw std::runtime_error("reduction order differs");++cases;}
  }
  // Real convolution-bias reductions include long post-filter sequences,
  // whose CUDA layout differs from the short latent Snake gradients.
  for(const auto& shape:std::vector<std::vector<int64_t>>{{1,2,65536},{1,2,65537},{1,2,524288},{1,108,258},{32,2,256},{1,512,256}}){
    auto input=at::randn(shape,at::TensorOptions().device(at::kCUDA));
    for(int strided=0;strided<2;++strided){auto x=strided?input.transpose(0,2):input;auto y=walloc::safe_broadcast_sum(x);
      if(!at::isfinite(y).all().item<bool>())throw std::runtime_error("nonfinite bias reduction");
      if(!safety&&!at::equal(y,at::sum(x,at::IntArrayRef({0,2}),true)))throw std::runtime_error("bias reduction order differs");++cases;}
  }
  auto options=at::TensorOptions().device(at::kCUDA);auto input=at::randn({1,2,65536},options),weight=at::randn({2,2,129},options),bias=at::randn({2},options);
  if(!at::equal(at::conv1d(input,weight,bias,{1},{64}),at::conv1d(input,weight,{}, {1},{64})+bias.view({1,-1,1})))throw std::runtime_error("convolution bias forward differs");
  at::detail::getCUDAHooks().deviceSynchronize(0);std::cout<<"PASS "<<cases<<" private sums; "<<(safety?"safety without unpatched kernel":"bit identical to pinned source primitive")<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
