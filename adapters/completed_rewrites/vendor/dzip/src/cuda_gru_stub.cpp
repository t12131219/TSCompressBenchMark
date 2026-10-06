#include "cuda_gru.hpp"
#include <stdexcept>
namespace dzip {
struct CudaGru::Impl {};
namespace { void unavailable() {throw std::runtime_error("CUDA training was not built; configure DZIP_WITH_CUDA=ON");} }
CudaGru::CudaGru(unsigned,unsigned,unsigned,unsigned,bool,const std::array<const float*,3>&) {unavailable();}
CudaGru::~CudaGru()=default;
std::vector<float> CudaGru::forward(const float*) {unavailable();return {};}
CudaGru::Gradients CudaGru::backward(const float*) {unavailable();return {};}
bool cuda_training_compiled() noexcept {return false;}
std::array<float,2> cuda_adam_powers(float,float,unsigned) {unavailable();return {};}
std::vector<float> cuda_sum(const float*,unsigned,unsigned,unsigned,bool) {unavailable();return {};}
std::vector<float> cuda_product(const float*,const float*,unsigned,unsigned,unsigned,bool,bool) {unavailable();return {};}
std::vector<float> cuda_softmax(const float*,unsigned,unsigned) {unavailable();return {};}
std::vector<float> cuda_softmax_gradient(const float*,const float*,unsigned,unsigned) {unavailable();return {};}
std::vector<float> cuda_embedding_gradient(const float*,const std::int32_t*,unsigned,unsigned,unsigned,float) {unavailable();return {};}
}
