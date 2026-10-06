#include "internal.hpp"
namespace deepzip {
bool cuda_available() noexcept {return false;}
std::vector<float> predict_cuda(const ModelData&,const std::vector<std::uint32_t>&) {
    throw Error(Status::unsupported,"this build has no CUDA prediction backend");
}
}
