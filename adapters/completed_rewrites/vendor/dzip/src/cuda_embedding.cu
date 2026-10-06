#include "cuda_gru.hpp"
#include <cuda_runtime.h>
#include <algorithm>
#include <stdexcept>
#include <string>

namespace dzip {
namespace {
void check(cudaError_t status) {if(status!=cudaSuccess)throw std::runtime_error(std::string("CUDA embedding: ")+cudaGetErrorString(status));}
struct Device {
    void* data=nullptr;
    explicit Device(std::size_t bytes) {check(cudaMalloc(&data,bytes));}
    ~Device() {if(data)cudaFree(data);}
    Device(const Device&)=delete;Device& operator=(const Device&)=delete;
};
struct Stream {
    cudaStream_t value=nullptr;
    Stream() {check(cudaStreamCreateWithFlags(&value,cudaStreamNonBlocking));}
    ~Stream() {if(value)cudaStreamDestroy(value);}
};
// The source represents embedding gradients as occurrence-indexed slices.
// Preserve its CUDA scatter-add operation, including clipping each slice
// before duplicate indices are merged. No source runtime executes here.
__global__ void accumulate(const float* slices,const std::int32_t* indices,float* output,
                           unsigned count,unsigned width,unsigned alphabet,float clipping) {
    for(unsigned i=blockIdx.x*blockDim.x+threadIdx.x;i<count;i+=gridDim.x*blockDim.x) {
        auto symbol=indices[i/width];
        if(symbol>=0 && unsigned(symbol)<alphabet)atomicAdd(output+unsigned(symbol)*width+i%width,slices[i]*clipping);
    }
}
__global__ void adam_powers(float beta1,float beta2,unsigned step,float* output) {
    output[0]=powf(beta1,float(step));output[1]=powf(beta2,float(step));
}
}
std::array<float,2> cuda_adam_powers(float beta1,float beta2,unsigned step) {
    Stream stream;Device result(2*sizeof(float));
    adam_powers<<<1,1,0,stream.value>>>(beta1,beta2,step,static_cast<float*>(result.data));check(cudaGetLastError());
    std::array<float,2> output{};check(cudaMemcpyAsync(output.data(),result.data,2*sizeof(float),cudaMemcpyDeviceToHost,stream.value));
    check(cudaStreamSynchronize(stream.value));return output;
}
std::vector<float> cuda_embedding_gradient(const float* slices,const std::int32_t* indices,
                                           unsigned rows,unsigned width,unsigned alphabet,float clipping) {
    if(!rows || rows>2048*64 || !width || width>32 || !alphabet || alphabet>256)
        throw std::invalid_argument("invalid CUDA embedding gradient dimensions");
    for(unsigned row=0;row<rows;++row)if(indices[row]<0 || unsigned(indices[row])>=alphabet)
        throw std::invalid_argument("CUDA embedding index outside alphabet");
    Stream stream;Device input(std::size_t(rows)*width*4),mapping(std::size_t(rows)*4),result(std::size_t(alphabet)*width*4);
    check(cudaMemcpyAsync(input.data,slices,std::size_t(rows)*width*4,cudaMemcpyHostToDevice,stream.value));
    check(cudaMemcpyAsync(mapping.data,indices,std::size_t(rows)*4,cudaMemcpyHostToDevice,stream.value));
    check(cudaMemsetAsync(result.data,0,std::size_t(alphabet)*width*4,stream.value));
    // Attribute queries have a stable ABI across the audited CUDA 10 runtime
    // and newer compiler headers; cudaDeviceProp's struct layout does not.
    int device=0,max_threads=0,multiprocessors=0,threads_per_sm=0;check(cudaGetDevice(&device));
    check(cudaDeviceGetAttribute(&max_threads,cudaDevAttrMaxThreadsPerBlock,device));
    check(cudaDeviceGetAttribute(&multiprocessors,cudaDevAttrMultiProcessorCount,device));
    check(cudaDeviceGetAttribute(&threads_per_sm,cudaDevAttrMaxThreadsPerMultiProcessor,device));
    unsigned count=rows*width,threads=unsigned(std::min(1024,max_threads));
    if(!threads || multiprocessors<=0 || threads_per_sm<=0)throw std::runtime_error("invalid CUDA launch attributes");
    unsigned blocks=std::min((count+threads-1)/threads,unsigned(multiprocessors*threads_per_sm)/threads);
    accumulate<<<blocks,threads,0,stream.value>>>(static_cast<const float*>(input.data),static_cast<const std::int32_t*>(mapping.data),
        static_cast<float*>(result.data),count,width,alphabet,clipping);
    check(cudaGetLastError());std::vector<float> output(std::size_t(alphabet)*width);
    check(cudaMemcpyAsync(output.data(),result.data,output.size()*4,cudaMemcpyDeviceToHost,stream.value));check(cudaStreamSynchronize(stream.value));return output;
}
}  // namespace dzip
