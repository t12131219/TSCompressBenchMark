// Private native primitive derived from pinned PyTorch2.6 Reduce.cuh;
// BSD-3-Clause notices in LICENSES/PyTorch-LICENSE.txt. No global dispatch override.
#include <ATen/ATen.h>
#include <ATen/native/ReduceOpsUtils.h>
#include "Reduce.cuh"
namespace walloc {
at::Tensor safe_broadcast_sum(const at::Tensor& gradient){
  TORCH_CHECK(gradient.is_cuda()&&gradient.scalar_type()==at::kFloat&&gradient.dim()==3,"invalid private CUDA sum");
  at::Tensor result=at::empty({1,gradient.size(1),1},gradient.options());
  auto iter=at::native::make_reduction("walloc_broadcast_sum",result,gradient,at::IntArrayRef({0,2}),true,at::kFloat);
  at::native::gpu_reduce_kernel<float,float>(iter,at::native::func_wrapper<float>([] GPU_LAMBDA(float a,float b)->float{return a+b;}));
  return result;
}
} // namespace walloc
