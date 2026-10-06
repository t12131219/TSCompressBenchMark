#include "cpu_ops.hpp"
#undef EIGEN_DONT_VECTORIZE
#define EIGEN_USE_THREADS
#define TENSORFLOW_USE_CUSTOM_CONTRACTION_KERNEL
#define TENSORFLOW_USE_MKLDNN_CONTRACTION_KERNEL
#include "../third_party/tf_cpu/eigen_contraction_kernel.h"
#include <mkldnn.h>
#include <stdexcept>
namespace Eigen {namespace internal {bool UseCustomContractionKernels() {return true;}}}
namespace dzip {
void cpu_adam(float* weight,float* m,float* v,const float* gradient,std::size_t count,
              float beta1,float beta2,float rate,float epsilon,bool sparse) {
    using Tensor=Eigen::Tensor<float,1,Eigen::RowMajor>;
    using ConstTensor=Eigen::Tensor<const float,1,Eigen::RowMajor>;
    Eigen::TensorMap<Tensor> w(weight,count),first(m,count),second(v,count);
    Eigen::TensorMap<ConstTensor> g(gradient,count);
    if(sparse) {
        first=first*beta1+g*(1.f-beta1);
        // Frozen Grappler pushes the scalar into the first factor of the
        // sparse Adam square: (g * (1-beta2)) * g. This differs by one ULP
        // from (g*g) * (1-beta2), even with bit-identical raw gradients.
        second=second*beta2+(g*(1.f-beta2))*g;
    } else {
        first=first+(g-first)*(1.f-beta1);
        second=second+(g.square()-second)*(1.f-beta2);
    }
    // The source's AVX Eigen sqrt uses reciprocal-sqrt plus one Newton step;
    // scalar std::sqrt differs and repeated online training amplifies it.
    w=w-(first*rate)/(second.sqrt()+epsilon);
}
std::vector<float> cpu_softmax(const float* input,unsigned rows,unsigned cols) {
    using ConstTensor=Eigen::Tensor<const float,2,Eigen::RowMajor>;
    using Tensor=Eigen::Tensor<float,2,Eigen::RowMajor>;
    std::vector<float> output(std::size_t(rows)*cols);
    Eigen::TensorMap<ConstTensor> logits(input,rows,cols);
    Eigen::TensorMap<Tensor> result(output.data(),rows,cols);
    Eigen::DefaultDevice device;
    Eigen::IndexList<Eigen::type2index<1>> along_class;
    Eigen::IndexList<int,Eigen::type2index<1>> batch_by_one;batch_by_one.set(0,int(rows));
    Eigen::IndexList<Eigen::type2index<1>,int> one_by_class;one_by_class.set(1,int(cols));
    result.device(device)=(logits-logits.maximum(along_class).eval().reshape(batch_by_one).broadcast(one_by_class)).exp();
    result.device(device)=result*result.sum(along_class).inverse().eval().reshape(batch_by_one).broadcast(one_by_class);
    return output;
}
std::vector<float> cpu_sum(const float* input,unsigned rows,unsigned cols,unsigned axis) {
    if(axis>1)throw std::invalid_argument("invalid CPU sum axis");
    Eigen::TensorMap<Eigen::Tensor<const float,2,Eigen::RowMajor>> values(input,rows,cols);
    std::vector<float> output(axis==0?cols:rows);
    Eigen::TensorMap<Eigen::Tensor<float,1,Eigen::RowMajor>> result(output.data(),output.size());
    thread_local Eigen::ThreadPool pool(1);Eigen::ThreadPoolDevice device(&pool,1);
    if(axis==0) {Eigen::IndexList<Eigen::type2index<0>> axes;result.device(device)=values.sum(axes);}
    else {Eigen::IndexList<Eigen::type2index<1>> axes;result.device(device)=values.sum(axes);}
    return output;
}
std::vector<float> cpu_product(const float* left,const float* right,unsigned rows,unsigned inner,unsigned cols,
                               bool transpose_left,bool transpose_right) {
    std::vector<float> result(std::size_t(rows)*cols,0.f);
    using ConstTensor=Eigen::Tensor<const float,2,Eigen::RowMajor>;
    using Tensor=Eigen::Tensor<float,2,Eigen::RowMajor>;
    Eigen::TensorMap<ConstTensor> a(left,transpose_left?inner:rows,transpose_left?rows:inner);
    Eigen::TensorMap<ConstTensor> b(right,transpose_right?cols:inner,transpose_right?inner:cols);
    Eigen::TensorMap<Tensor> c(result.data(),rows,cols);
    thread_local Eigen::ThreadPool pool(1);
    Eigen::ThreadPoolDevice device(&pool,1);
    Eigen::array<Eigen::IndexPair<int>,1> axes{{Eigen::IndexPair<int>(transpose_left?0:1,transpose_right?1:0)}};
    c.device(device)=a.contract(b,axes);
    return result;
}
}
