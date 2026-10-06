#define EIGEN_USE_GPU
#include "cuda_gru.hpp"
#include <unsupported/Eigen/CXX11/Tensor>
#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

namespace dzip {
namespace {
void check(cudaError_t status) {
    if(status!=cudaSuccess)throw std::runtime_error(std::string("CUDA reduction: ")+cudaGetErrorString(status));
}
// The compiler and audited runtime have different cudaDeviceProp layouts.
// Build the properties consumed by Eigen from stable attribute queries.
class Stream final:public Eigen::StreamInterface {
    cudaStream_t stream_=nullptr;cudaDeviceProp properties_{};void* scratch_=nullptr;
public:
    Stream() {
        int device=0;check(cudaGetDevice(&device));
        auto attribute=[&](int& target,cudaDeviceAttr name){check(cudaDeviceGetAttribute(&target,name,device));};
        attribute(properties_.major,cudaDevAttrComputeCapabilityMajor);
        attribute(properties_.minor,cudaDevAttrComputeCapabilityMinor);
        attribute(properties_.multiProcessorCount,cudaDevAttrMultiProcessorCount);
        attribute(properties_.maxThreadsPerBlock,cudaDevAttrMaxThreadsPerBlock);
        attribute(properties_.maxThreadsPerMultiProcessor,cudaDevAttrMaxThreadsPerMultiProcessor);
        attribute(properties_.maxGridSize[0],cudaDevAttrMaxGridDimX);
        attribute(properties_.maxGridSize[1],cudaDevAttrMaxGridDimY);
        attribute(properties_.maxGridSize[2],cudaDevAttrMaxGridDimZ);
        check(cudaStreamCreateWithFlags(&stream_,cudaStreamNonBlocking));
        try {check(cudaMalloc(&scratch_,Eigen::kGpuScratchSize+sizeof(unsigned)));
             check(cudaMemsetAsync(scratch_,0,Eigen::kGpuScratchSize+sizeof(unsigned),stream_));}
        catch(...) {if(scratch_)cudaFree(scratch_);cudaStreamDestroy(stream_);throw;}
    }
    ~Stream() override {if(scratch_)cudaFree(scratch_);if(stream_)cudaStreamDestroy(stream_);}
    const cudaStream_t& stream() const override {return stream_;}
    const cudaDeviceProp& deviceProperties() const override {return properties_;}
    void* allocate(std::size_t size) const override {
        if(size>1024ull*1024*1024)throw std::invalid_argument("CUDA reduction allocation exceeds limit");
        void* output=nullptr;check(cudaMalloc(&output,size));return output;
    }
    void deallocate(void* pointer) const override {if(pointer)cudaFree(pointer);}
    void* scratchpad() const override {return scratch_;}
    unsigned* semaphore() const override {return reinterpret_cast<unsigned*>(static_cast<char*>(scratch_)+Eigen::kGpuScratchSize);}
};
struct Memory {
    void* data=nullptr;
    explicit Memory(std::size_t size) {check(cudaMalloc(&data,size));}
    ~Memory() {if(data)cudaFree(data);}
    Memory(const Memory&)=delete;Memory& operator=(const Memory&)=delete;
};
}
std::vector<float> cuda_sum(const float* input,unsigned rows,unsigned cols,unsigned axis,bool squared) {
    if(!rows || !cols || std::uint64_t(rows)*cols>268435456 || axis>2)
        throw std::invalid_argument("invalid CUDA reduction dimensions");
    Stream stream;Eigen::GpuDevice device(&stream);unsigned count=axis==2?1:axis==0?cols:rows;
    Memory source(std::size_t(rows)*cols*4),target(std::size_t(count)*4);
    check(cudaMemcpyAsync(source.data,input,std::size_t(rows)*cols*4,cudaMemcpyHostToDevice,stream.stream()));
    using ConstTensor=Eigen::Tensor<const float,2,Eigen::RowMajor,int>;
    Eigen::TensorMap<ConstTensor> values(static_cast<float*>(source.data),int(rows),int(cols));
    if(axis==2) {
        Eigen::TensorMap<Eigen::Tensor<float,0,Eigen::RowMajor,int>> result(static_cast<float*>(target.data));
        Eigen::array<int,2> axes{{0,1}};
        if(squared)result.device(device)=values.square().sum(axes);
        else result.device(device)=values.sum(axes);
    } else {
        Eigen::TensorMap<Eigen::Tensor<float,1,Eigen::RowMajor,int>> result(static_cast<float*>(target.data),int(count));
        Eigen::array<int,1> axes{{int(axis)}};
        if(squared)result.device(device)=values.square().sum(axes);
        else result.device(device)=values.sum(axes);
    }
    check(cudaGetLastError());std::vector<float> output(count);
    check(cudaMemcpyAsync(output.data(),target.data,std::size_t(count)*4,cudaMemcpyDeviceToHost,stream.stream()));
    check(cudaStreamSynchronize(stream.stream()));return output;
}
}
