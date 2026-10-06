#pragma once
#include <vector>
#include <cstddef>
namespace dzip {
std::vector<float> cpu_product(const float* left,const float* right,unsigned rows,unsigned inner,unsigned cols,
                               bool transpose_left,bool transpose_right);
std::vector<float> cpu_softmax(const float* input,unsigned rows,unsigned cols);
std::vector<float> cpu_sum(const float* input,unsigned rows,unsigned cols,unsigned axis);
void cpu_adam(float* weight,float* m,float* v,const float* gradient,std::size_t count,
              float beta1,float beta2,float rate,float epsilon,bool sparse);
}
