// Native CUDA prediction; no Python, TensorFlow or Keras calls.
#include "internal.hpp"
#include <cuda_fp16.h>
#include <cuda_runtime.h>

namespace deepzip {
namespace {
void cuda_check(cudaError_t status,const char* operation) {
    if(status!=cudaSuccess) throw Error(Status::device_failure,std::string(operation)+": "+cudaGetErrorString(status));
}
template<class T> class Device {
public:
    explicit Device(std::size_t count):count_(count) {
        cuda_check(cudaMalloc(reinterpret_cast<void**>(&pointer_),checked_mul(count,sizeof(T))),"cudaMalloc");
    }
    explicit Device(const std::vector<T>& input):Device(input.size()) {
        cuda_check(cudaMemcpy(pointer_,input.data(),count_*sizeof(T),cudaMemcpyHostToDevice),"cudaMemcpy weights/input");
    }
    ~Device(){if(pointer_) cudaFree(pointer_);}
    Device(Device&& other) noexcept:pointer_(other.pointer_),count_(other.count_) {other.pointer_=nullptr;}
    Device& operator=(Device&& other) noexcept {
        if(this!=&other){if(pointer_) cudaFree(pointer_);pointer_=other.pointer_;count_=other.count_;other.pointer_=nullptr;}
        return *this;
    }
    Device(const Device&)=delete;
    Device& operator=(const Device&)=delete;
    T* get() const{return pointer_;}
    std::vector<T> download() const {
        std::vector<T> result(count_);
        cuda_check(cudaMemcpy(result.data(),pointer_,count_*sizeof(T),cudaMemcpyDeviceToHost),"cudaMemcpy probabilities");
        return result;
    }
private:
    T* pointer_=nullptr;
    std::size_t count_;
};
__device__ float quantize(float x,bool half) {return half?__half2float(__float2half_rn(x)):x;}
__device__ float logistic(float x) {return 1.0f/(1.0f+expf(-x));}
__global__ void embedding(const unsigned* ids,const float* weights,float* out,std::size_t total,unsigned features) {
    std::size_t i=static_cast<std::size_t>(blockIdx.x)*blockDim.x+threadIdx.x;
    if(i<total) out[i]=weights[static_cast<std::size_t>(ids[i/features])*features+i%features];
}
__global__ void dense(const float* in,const float* kernel,const float* bias,float* out,
                      std::size_t total,unsigned features,unsigned width,unsigned activation,bool half) {
    std::size_t i=static_cast<std::size_t>(blockIdx.x)*blockDim.x+threadIdx.x;
    if(i>=total) return;
    auto row=i/width,j=i%width;
    float sum=0;
    for(unsigned k=0;k<features;++k) sum+=in[row*features+k]*kernel[static_cast<std::size_t>(k)*width+j];
    float v=quantize(quantize(sum,half)+bias[j],half);
    if(activation==1) v=fmaxf(0,v);
    if(activation==2 && v<0) v=expm1f(v);
    if(activation==3) v=1.0507009873554805f*(v>=0?v:1.6732632423543772f*expm1f(v));
    out[i]=quantize(v,half);
}
__global__ void softmax(float* values,unsigned width,bool half) {
    auto offset=static_cast<std::size_t>(blockIdx.x)*width;
    float maximum=values[offset];
    for(unsigned j=1;j<width;++j) maximum=fmaxf(maximum,values[offset+j]);
    float sum=0;
    for(unsigned j=0;j<width;++j) {values[offset+j]=expf(values[offset+j]-maximum);sum+=values[offset+j];}
    for(unsigned j=0;j<width;++j) values[offset+j]=quantize(values[offset+j]/sum,half);
}
__global__ void batchnorm(float* values,const float* gamma,const float* beta,const float* mean,const float* variance,
                          std::size_t total,unsigned features,float epsilon,bool half) {
    std::size_t i=static_cast<std::size_t>(blockIdx.x)*blockDim.x+threadIdx.x;
    if(i<total) {
        auto j=i%features;
        float scale=gamma[j]/sqrtf(variance[j]+epsilon);
        values[i]=quantize((values[i]-mean[j])*scale+beta[j],half);
    }
}
__global__ void recurrent(const float* values,float* result,const float* kernel0,const float* recurrent0,const float* bias0,
                          const float* kernel1,const float* recurrent1,const float* bias1,
                          unsigned steps,unsigned features,unsigned units,unsigned gates,
                          unsigned directions,bool sequence,bool half) {
    unsigned b=blockIdx.x/directions,d=blockIdx.x%directions,j=threadIdx.x;
    const float* kernel=d?kernel1:kernel0;
    const float* hidden_kernel=d?recurrent1:recurrent0;
    const float* bias=d?bias1:bias0;
    __shared__ float hidden[128];
    __shared__ float cell[128];
    hidden[j]=0;cell[j]=0;
    __syncthreads();
    for(unsigned step=0;step<steps;++step) {
        unsigned time=d?steps-step-1:step;
        float input_sum[4],hidden_sum[4];
        for(unsigned gate=0;gate<gates;++gate) {
            float in=0,rec=0;
            for(unsigned k=0;k<features;++k) {
                unsigned packed=j*features+k;
                in+=values[(static_cast<std::size_t>(b)*steps+time)*features+k]*
                    kernel[(packed/units)*units*gates+gate*units+packed%units];
            }
            for(unsigned k=0;k<units;++k) rec+=hidden[k]*hidden_kernel[j*units*gates+gate*units+k];
            input_sum[gate]=quantize(in+bias[gate*units+j],half);
            hidden_sum[gate]=quantize(rec+bias[units*gates+gate*units+j],half);
        }
        // Every thread finishes reading the old hidden vector before writes.
        __syncthreads();
        if(gates==3) {
            float z=quantize(logistic(quantize(input_sum[0]+hidden_sum[0],half)),half);
            float r=quantize(logistic(quantize(input_sum[1]+hidden_sum[1],half)),half);
            float n=quantize(tanhf(quantize(input_sum[2]+quantize(r*hidden_sum[2],half),half)),half);
            hidden[j]=quantize(quantize(z*hidden[j],half)+quantize(quantize(1-z,half)*n,half),half);
        } else {
            float in=quantize(logistic(quantize(input_sum[0]+hidden_sum[0],half)),half);
            float forget=quantize(logistic(quantize(input_sum[1]+hidden_sum[1],half)),half);
            float candidate=quantize(tanhf(quantize(input_sum[2]+hidden_sum[2],half)),half);
            float out=quantize(logistic(quantize(input_sum[3]+hidden_sum[3],half)),half);
            cell[j]=quantize(quantize(forget*cell[j],half)+quantize(in*candidate,half),half);
            hidden[j]=quantize(out*quantize(tanhf(cell[j]),half),half);
        }
        __syncthreads();
        if(sequence) result[(static_cast<std::size_t>(b)*steps+time)*units*directions+d*units+j]=hidden[j];
    }
    if(!sequence) result[static_cast<std::size_t>(b)*units*directions+d*units+j]=hidden[j];
}
}
bool cuda_available() noexcept {int count=0;return cudaGetDeviceCount(&count)==cudaSuccess && count>0;}
std::vector<float> predict_cuda(const ModelData& model,const std::vector<std::uint32_t>& contexts) {
    require(cuda_available(),Status::device_failure,"no CUDA device available");
    unsigned batch=static_cast<unsigned>(contexts.size()/64),steps=64,features=0;
    Device<unsigned> ids(contexts);
    // Initial allocation is replaced by the embedding output.
    Device<float> values(1);
    for(const auto& l:model.layers) {
        bool half=l.flags&4;
        std::vector<Device<float>> weights;weights.reserve(l.tensors.size());
        for(const auto& tensor:l.tensors) weights.emplace_back(tensor.data);
        if(l.kind==1) {
            features=l.tensors[0].shape[1];
            std::size_t total=static_cast<std::size_t>(batch)*steps*features;
            Device<float> output(total);
            embedding<<<static_cast<unsigned>((total+127)/128),128>>>(ids.get(),weights[0].get(),output.get(),total,features);
            values=std::move(output);
        } else if(l.kind==5) {
            features*=steps;steps=1;
        } else if(l.kind==6) {
            auto total=static_cast<std::size_t>(batch)*features;
            batchnorm<<<static_cast<unsigned>((total+127)/128),128>>>(values.get(),weights[0].get(),weights[1].get(),weights[2].get(),weights[3].get(),total,features,l.epsilon,half);
        } else if(l.kind==4) {
            auto width=l.tensors[1].shape[0];
            auto total=static_cast<std::size_t>(batch)*width;
            Device<float> output(total);
            dense<<<static_cast<unsigned>((total+127)/128),128>>>(values.get(),weights[0].get(),weights[1].get(),output.get(),total,features,width,l.activation,half);
            if(l.activation==4) softmax<<<batch,1>>>(output.get(),width,half);
            values=std::move(output);features=width;
        } else {
            auto units=l.tensors[1].shape[0];unsigned directions=(l.flags&2)?2:1,gates=l.kind==2?3:4;
            unsigned out_steps=(l.flags&1)?steps:1;
            Device<float> output(static_cast<std::size_t>(batch)*out_steps*units*directions);
            recurrent<<<batch*directions,units>>>(values.get(),output.get(),weights[0].get(),weights[1].get(),weights[2].get(),
                directions==2?weights[3].get():nullptr,directions==2?weights[4].get():nullptr,directions==2?weights[5].get():nullptr,
                steps,features,units,gates,directions,l.flags&1,half);
            values=std::move(output);steps=out_steps;features=units*directions;
        }
        cuda_check(cudaGetLastError(),"CUDA prediction kernel launch");
        // Complete kernels before their layer weights are released.
        cuda_check(cudaDeviceSynchronize(),"CUDA prediction layer synchronization");
    }
    auto result=values.download();
    require(std::all_of(result.begin(),result.end(),[](float v){return std::isfinite(v)&&v>=0&&v<=1;}),
            Status::invalid_model,"CUDA predictor produced invalid probabilities");
    return result;
}
}  // namespace deepzip
