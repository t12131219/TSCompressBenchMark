#include "cuda_gru.hpp"
#include <cuda_runtime_api.h>
#include <cublas_v2.h>
#include <cudnn.h>
#include <algorithm>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>

namespace dzip {
namespace {
void check(cudaError_t status) {if(status!=cudaSuccess) throw std::runtime_error(std::string("CUDA: ")+cudaGetErrorString(status));}
void check(cudnnStatus_t status) {if(status!=CUDNN_STATUS_SUCCESS) throw std::runtime_error(std::string("cuDNN: ")+cudnnGetErrorString(status));}
void check(cublasStatus_t status) {if(status!=CUBLAS_STATUS_SUCCESS) throw std::runtime_error("cuBLAS operation failed: "+std::to_string(int(status)));}
void need(bool ok,const char* message) {if(!ok) throw std::invalid_argument(message);}
struct Memory {
    void* pointer=nullptr;
    ~Memory() {if(pointer) cudaFree(pointer);}
    Memory()=default;Memory(const Memory&)=delete;Memory& operator=(const Memory&)=delete;
    void allocate(std::size_t bytes) {
        need(!pointer && bytes<=1024ull*1024*1024,"CUDA allocation exceeds limit");
        if(bytes) check(cudaMalloc(&pointer,bytes));
    }
};
template<class T,auto Destroy> struct Descriptor {
    T value=nullptr;
    ~Descriptor() {if(value) Destroy(value);}
    Descriptor()=default;Descriptor(const Descriptor&)=delete;Descriptor& operator=(const Descriptor&)=delete;
};
struct Stream {
    cudaStream_t value=nullptr;
    Stream() {check(cudaStreamCreateWithFlags(&value,cudaStreamNonBlocking));}
    ~Stream() {if(value) cudaStreamDestroy(value);}
};
using Handle=Descriptor<cudnnHandle_t,cudnnDestroy>;
using Tensor=Descriptor<cudnnTensorDescriptor_t,cudnnDestroyTensorDescriptor>;
using Filter=Descriptor<cudnnFilterDescriptor_t,cudnnDestroyFilterDescriptor>;
using Rnn=Descriptor<cudnnRNNDescriptor_t,cudnnDestroyRNNDescriptor>;
using Dropout=Descriptor<cudnnDropoutDescriptor_t,cudnnDestroyDropoutDescriptor>;
using Blas=Descriptor<cublasHandle_t,cublasDestroy_v2>;
std::size_t bytes(std::uint64_t count) {
    need(count<=1024ull*1024*1024/sizeof(float),"CUDA tensor exceeds limit");
    return std::size_t(count)*sizeof(float);
}
void tensor(Tensor& descriptor,unsigned a,unsigned b,unsigned c) {
    check(cudnnCreateTensorDescriptor(&descriptor.value));
    int dims[]{int(a),int(b),int(c)},strides[]{int(b*c),int(c),1};
    check(cudnnSetTensorNdDescriptor(descriptor.value,CUDNN_DATA_FLOAT,3,dims,strides));
}
}

struct CudaGru::Impl {
    unsigned batch,steps,features,units;bool reverse,ready=false,consumed=false;
    Stream stream;Handle handle;Tensor xdesc,ydesc,hdesc;Filter wdesc;Rnn rnn;Dropout dropout;
    Memory dropout_state,x,y,h,w,workspace,reserve;
    std::size_t wbytes=0,workbytes=0,reservebytes=0;
    std::vector<cudnnTensorDescriptor_t> xs,ys;
    std::array<std::size_t,6> matrix_offsets{},bias_offsets{};
    Impl(unsigned b,unsigned s,unsigned f,unsigned u,bool rev,const std::array<const float*,3>& weights)
        :batch(b),steps(s),features(f),units(u),reverse(rev) {
        need(batch>0 && batch<=2048 && steps==64 && features<=256 && features>0 && units>0 && units<=128,
             "unsupported CUDA GRU dimensions");
        check(cudnnCreate(&handle.value));check(cudnnSetStream(handle.value,stream.value));
        tensor(xdesc,batch,features,1);tensor(ydesc,batch,units,1);tensor(hdesc,1,batch,units);
        xs.assign(steps,xdesc.value);ys.assign(steps,ydesc.value);
        check(cudnnCreateDropoutDescriptor(&dropout.value));std::size_t statebytes=0;
        check(cudnnDropoutGetStatesSize(handle.value,&statebytes));dropout_state.allocate(statebytes);
        check(cudnnSetDropoutDescriptor(dropout.value,handle.value,0.f,dropout_state.pointer,statebytes,0));
        check(cudnnCreateRNNDescriptor(&rnn.value));
        check(cudnnSetRNNDescriptor(handle.value,rnn.value,int(units),1,dropout.value,
                                   CUDNN_LINEAR_INPUT,CUDNN_UNIDIRECTIONAL,CUDNN_GRU,CUDNN_RNN_ALGO_STANDARD,CUDNN_DATA_FLOAT));
        check(cudnnSetRNNMatrixMathType(rnn.value,CUDNN_DEFAULT_MATH));
        check(cudnnGetRNNParamsSize(handle.value,rnn.value,xdesc.value,&wbytes,CUDNN_DATA_FLOAT));
        need(wbytes%4==0 && wbytes/4<=unsigned(std::numeric_limits<int>::max()),"invalid CUDA weight layout");
        w.allocate(wbytes);check(cudnnCreateFilterDescriptor(&wdesc.value));
        int dims[]{int(wbytes/4),1,1};check(cudnnSetFilterNdDescriptor(wdesc.value,CUDNN_DATA_FLOAT,CUDNN_TENSOR_NCHW,3,dims));
        std::vector<float> packed(wbytes/4,0);
        for(unsigned layer=0;layer<6;++layer) {
            // cuDNN r,z,h -> canonical z,r,h, separately for W and R.
            unsigned gate=layer%3==0?1:layer%3==1?0:2,width=layer<3?features:units;
            Filter matrix,bias;void* address=nullptr;
            check(cudnnCreateFilterDescriptor(&matrix.value));
            check(cudnnGetRNNLinLayerMatrixParams(handle.value,rnn.value,0,xdesc.value,wdesc.value,w.pointer,int(layer),matrix.value,&address));
            auto start=reinterpret_cast<std::uintptr_t>(w.pointer),current=reinterpret_cast<std::uintptr_t>(address);
            need(current>=start && (current-start)%4==0,"invalid CUDA parameter address");
            auto offset=(current-start)/4;
            need(offset<=packed.size() && std::size_t(width)*units<=packed.size()-offset,"invalid CUDA matrix offset");
            matrix_offsets[layer]=std::size_t(offset);
            for(unsigned row=0;row<units;++row) for(unsigned col=0;col<width;++col)
                packed[std::size_t(offset)+row*width+col]=weights[layer<3?0:1][col*3*units+gate*units+row];
            check(cudnnCreateFilterDescriptor(&bias.value));
            check(cudnnGetRNNLinLayerBiasParams(handle.value,rnn.value,0,xdesc.value,wdesc.value,w.pointer,int(layer),bias.value,&address));
            current=reinterpret_cast<std::uintptr_t>(address);
            need(current>=start && (current-start)%4==0,"invalid CUDA bias address");
            offset=(current-start)/4;
            need(offset<=packed.size() && units<=packed.size()-offset,"invalid CUDA bias offset");
            bias_offsets[layer]=std::size_t(offset);
            std::copy_n(weights[2]+(layer/3)*3*units+gate*units,units,packed.data()+offset);
        }
        check(cudaMemcpyAsync(w.pointer,packed.data(),wbytes,cudaMemcpyHostToDevice,stream.value));
        x.allocate(bytes(std::uint64_t(batch)*steps*features));y.allocate(bytes(std::uint64_t(batch)*steps*units));h.allocate(bytes(std::uint64_t(batch)*units));
        check(cudaMemsetAsync(h.pointer,0,bytes(std::uint64_t(batch)*units),stream.value));
        check(cudnnGetRNNWorkspaceSize(handle.value,rnn.value,int(steps),xs.data(),&workbytes));
        check(cudnnGetRNNTrainingReserveSize(handle.value,rnn.value,int(steps),xs.data(),&reservebytes));
        workspace.allocate(workbytes);reserve.allocate(reservebytes);check(cudaStreamSynchronize(stream.value));
    }
    std::vector<float> time_major(const float* input,unsigned width) const {
        std::vector<float> result(std::size_t(batch)*steps*width);
        for(unsigned tick=0;tick<steps;++tick) for(unsigned row=0;row<batch;++row)
            std::copy_n(input+(std::size_t(row)*steps+(reverse?steps-1-tick:tick))*width,width,
                        result.data()+(std::size_t(tick)*batch+row)*width);
        return result;
    }
    std::vector<float> batch_major(const std::vector<float>& input,unsigned width) const {
        std::vector<float> result(input.size());
        for(unsigned tick=0;tick<steps;++tick) for(unsigned row=0;row<batch;++row)
            std::copy_n(input.data()+(std::size_t(tick)*batch+row)*width,width,
                        result.data()+(std::size_t(row)*steps+(reverse?steps-1-tick:tick))*width);
        return result;
    }
};
CudaGru::CudaGru(unsigned b,unsigned s,unsigned f,unsigned u,bool reverse,const std::array<const float*,3>& weights)
    :impl_(std::make_unique<Impl>(b,s,f,u,reverse,weights)) {}
CudaGru::~CudaGru()=default;
std::vector<float> CudaGru::forward(const float* input) {
    auto& p=*impl_;need(!p.ready,"CUDA GRU forward cache already populated");
    auto ordered=p.time_major(input,p.features);
    check(cudaMemcpyAsync(p.x.pointer,ordered.data(),bytes(ordered.size()),cudaMemcpyHostToDevice,p.stream.value));
    check(cudnnRNNForwardTraining(p.handle.value,p.rnn.value,int(p.steps),p.xs.data(),p.x.pointer,p.hdesc.value,p.h.pointer,
         nullptr,nullptr,p.wdesc.value,p.w.pointer,p.ys.data(),p.y.pointer,p.hdesc.value,nullptr,nullptr,nullptr,
         p.workspace.pointer,p.workbytes,p.reserve.pointer,p.reservebytes));
    std::vector<float> output(std::size_t(p.batch)*p.steps*p.units);
    check(cudaMemcpyAsync(output.data(),p.y.pointer,bytes(output.size()),cudaMemcpyDeviceToHost,p.stream.value));
    check(cudaStreamSynchronize(p.stream.value));p.ready=true;return p.batch_major(output,p.units);
}
CudaGru::Gradients CudaGru::backward(const float* gradient) {
    auto& p=*impl_;need(p.ready && !p.consumed,"CUDA GRU backward needs an unconsumed forward cache");
    auto ordered=p.time_major(gradient,p.units);Memory dy,dx,dw;
    dy.allocate(bytes(ordered.size()));dx.allocate(bytes(std::uint64_t(p.batch)*p.steps*p.features));dw.allocate(p.wbytes);
    check(cudaMemcpyAsync(dy.pointer,ordered.data(),bytes(ordered.size()),cudaMemcpyHostToDevice,p.stream.value));
    check(cudaMemsetAsync(dw.pointer,0,p.wbytes,p.stream.value));
    check(cudnnRNNBackwardData(p.handle.value,p.rnn.value,int(p.steps),p.ys.data(),p.y.pointer,p.ys.data(),dy.pointer,
         p.hdesc.value,nullptr,nullptr,nullptr,p.wdesc.value,p.w.pointer,p.hdesc.value,p.h.pointer,nullptr,nullptr,
         p.xs.data(),dx.pointer,p.hdesc.value,nullptr,nullptr,nullptr,p.workspace.pointer,p.workbytes,p.reserve.pointer,p.reservebytes));
    check(cudnnRNNBackwardWeights(p.handle.value,p.rnn.value,int(p.steps),p.xs.data(),p.x.pointer,p.hdesc.value,p.h.pointer,
         p.ys.data(),p.y.pointer,p.workspace.pointer,p.workbytes,p.wdesc.value,dw.pointer,p.reserve.pointer,p.reservebytes));
    std::vector<float> input(std::size_t(p.batch)*p.steps*p.features),packed(p.wbytes/4);
    check(cudaMemcpyAsync(input.data(),dx.pointer,bytes(input.size()),cudaMemcpyDeviceToHost,p.stream.value));
    check(cudaMemcpyAsync(packed.data(),dw.pointer,p.wbytes,cudaMemcpyDeviceToHost,p.stream.value));check(cudaStreamSynchronize(p.stream.value));
    Gradients result{p.batch_major(input,p.features),std::vector<float>(std::size_t(p.features)*3*p.units),
                     std::vector<float>(std::size_t(p.units)*3*p.units),std::vector<float>(6*p.units)};
    for(unsigned layer=0;layer<6;++layer) {
        unsigned gate=layer%3==0?1:layer%3==1?0:2,width=layer<3?p.features:p.units;
        auto& target=layer<3?result.kernel:result.recurrent;
        for(unsigned row=0;row<p.units;++row) for(unsigned col=0;col<width;++col)
            target[col*3*p.units+gate*p.units+row]=packed[p.matrix_offsets[layer]+row*width+col];
        std::copy_n(packed.data()+p.bias_offsets[layer],p.units,result.bias.data()+(layer/3)*3*p.units+gate*p.units);
    }
    p.consumed=true;return result;
}
bool cuda_training_compiled() noexcept {return true;}
std::vector<float> cuda_product(const float* left,const float* right,unsigned rows,unsigned inner,unsigned cols,bool transpose_left,bool transpose_right) {
    need(rows && rows<=131072 && inner && inner<=8192 && cols && cols<=8192,"invalid CUDA product dimensions");
    Stream stream;Blas handle;check(cublasCreate(&handle.value));check(cublasSetStream(handle.value,stream.value));
    Memory a,b,c;a.allocate(bytes(std::uint64_t(rows)*inner));b.allocate(bytes(std::uint64_t(inner)*cols));c.allocate(bytes(std::uint64_t(rows)*cols));
    check(cudaMemcpyAsync(a.pointer,left,bytes(std::uint64_t(rows)*inner),cudaMemcpyHostToDevice,stream.value));
    check(cudaMemcpyAsync(b.pointer,right,bytes(std::uint64_t(inner)*cols),cudaMemcpyHostToDevice,stream.value));
    const float alpha=1.f,beta=0.f;
    check(cublasSgemm(handle.value,transpose_right?CUBLAS_OP_T:CUBLAS_OP_N,transpose_left?CUBLAS_OP_T:CUBLAS_OP_N,int(cols),int(rows),int(inner),&alpha,
                      static_cast<const float*>(b.pointer),int(transpose_right?inner:cols),static_cast<const float*>(a.pointer),int(transpose_left?rows:inner),&beta,
                      static_cast<float*>(c.pointer),int(cols)));
    std::vector<float> result(std::size_t(rows)*cols);
    check(cudaMemcpyAsync(result.data(),c.pointer,bytes(result.size()),cudaMemcpyDeviceToHost,stream.value));check(cudaStreamSynchronize(stream.value));
    return result;
}
namespace {
std::vector<float> softmax_operation(const float* input,const float* output,unsigned rows,unsigned cols) {
    need(rows>0 && rows<=2048 && cols>0 && cols<=256,"invalid CUDA softmax dimensions");
    Stream stream;Handle handle;check(cudnnCreate(&handle.value));check(cudnnSetStream(handle.value,stream.value));
    Tensor desc;check(cudnnCreateTensorDescriptor(&desc.value));
    check(cudnnSetTensor4dDescriptor(desc.value,CUDNN_TENSOR_NCHW,CUDNN_DATA_FLOAT,int(rows),int(cols),1,1));
    Memory x,y,z;auto length=bytes(std::uint64_t(rows)*cols);x.allocate(length);y.allocate(length);z.allocate(length);
    check(cudaMemcpyAsync(x.pointer,input,length,cudaMemcpyHostToDevice,stream.value));
    const float one=1.f,zero=0.f;
    if(output) {
        check(cudaMemcpyAsync(y.pointer,output,length,cudaMemcpyHostToDevice,stream.value));
        check(cudnnSoftmaxBackward(handle.value,CUDNN_SOFTMAX_ACCURATE,CUDNN_SOFTMAX_MODE_INSTANCE,
             &one,desc.value,y.pointer,desc.value,x.pointer,&zero,desc.value,z.pointer));
    } else {
        check(cudnnSoftmaxForward(handle.value,CUDNN_SOFTMAX_ACCURATE,CUDNN_SOFTMAX_MODE_INSTANCE,
             &one,desc.value,x.pointer,&zero,desc.value,z.pointer));
    }
    std::vector<float> result(std::size_t(rows)*cols);
    check(cudaMemcpyAsync(result.data(),z.pointer,length,cudaMemcpyDeviceToHost,stream.value));check(cudaStreamSynchronize(stream.value));return result;
}
}
std::vector<float> cuda_softmax(const float* input,unsigned rows,unsigned cols) {return softmax_operation(input,nullptr,rows,cols);}
std::vector<float> cuda_softmax_gradient(const float* gradient,const float* output,unsigned rows,unsigned cols) {return softmax_operation(gradient,output,rows,cols);}
}  // namespace dzip
