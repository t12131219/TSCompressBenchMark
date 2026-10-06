#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <vector>

namespace dzip {
// Native cuDNN executor for one source CuDNNGRU direction. All recurrent
// forward/data-gradient/weight-gradient work runs on the selected CUDA device.
// Host graph tensors use [batch,time,feature] and canonical z,r,h gate order.
class CudaGru {
public:
    CudaGru(unsigned batch,unsigned steps,unsigned features,unsigned units,
            bool reverse,const std::array<const float*,3>& weights);
    ~CudaGru();
    CudaGru(const CudaGru&)=delete;
    CudaGru& operator=(const CudaGru&)=delete;
    std::vector<float> forward(const float* input);
    struct Gradients {
        std::vector<float> input,kernel,recurrent,bias;
    };
    Gradients backward(const float* gradient);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
bool cuda_training_compiled() noexcept;
std::array<float,2> cuda_adam_powers(float beta1,float beta2,unsigned step);
// axis=0 columns, axis=1 rows, axis=2 entire tensor; source Eigen reductions.
std::vector<float> cuda_sum(const float* input,unsigned rows,unsigned cols,unsigned axis,bool squared=false);
std::vector<float> cuda_product(const float* left,const float* right,
                                unsigned rows,unsigned inner,unsigned cols,
                                bool transpose_left=false,bool transpose_right=false);
std::vector<float> cuda_softmax(const float* input,unsigned rows,unsigned cols);
std::vector<float> cuda_softmax_gradient(const float* gradient,const float* output,
                                        unsigned rows,unsigned cols);
std::vector<float> cuda_embedding_gradient(const float* slices,const std::int32_t* indices,
                                           unsigned rows,unsigned width,unsigned alphabet,float clipping);
}  // namespace dzip
