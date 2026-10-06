#include "dzip_nn.hpp"
#include "cuda_gru.hpp"
#include "cpu_ops.hpp"
#include <Eigen/Core>
#include <unsupported/Eigen/CXX11/Tensor>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <mutex>
#include <random>
#include <stdexcept>
#include <utility>

namespace dzip {
namespace {
using Matrix = Eigen::Matrix<float,Eigen::Dynamic,Eigen::Dynamic,Eigen::RowMajor>;
void need(bool ok,const char* message) { if(!ok) throw std::invalid_argument(message); }
std::unique_lock<std::mutex> cuda_call_guard(ExecutionBackend backend) {
    // The frozen CUDA 10/cuDNN 7 backend cannot complete concurrent calls
    // under full racecheck. Serialize actual GPU operations at the public
    // API boundary, retaining independent model/optimizer state and all
    // kernels. CPU handles remain independent and execute concurrently.
    static std::mutex mutex;
    std::unique_lock<std::mutex> guard(mutex,std::defer_lock);
    if(backend==ExecutionBackend::cuda)guard.lock();
    return guard;
}
struct Reader {
    const Bytes& bytes; std::size_t pos=0;
    unsigned word() {
        need(bytes.size()-pos>=4,"truncated model");
        unsigned result=0; for(unsigned i=0;i<4;++i) result|=unsigned(bytes[pos++])<<(i*8);
        return result;
    }
    float real() { auto bits=word(); float value; std::memcpy(&value,&bits,4);need(std::isfinite(value),"nonfinite model weight");return value; }
};
void word(Bytes& bytes,unsigned value) { for(unsigned i=0;i<4;++i) bytes.push_back(std::uint8_t(value>>(i*8))); }
struct Tensor { std::vector<unsigned> shape; Matrix weight,gradient,m,v; };
struct Node { unsigned kind=0,activation=0;std::vector<unsigned> inputs;std::vector<Tensor> tensors;unsigned steps=0,features=0; };
struct Step { Matrix x,previous,z,r,candidate,recurrent; };
struct Value { Matrix data,gradient;std::array<std::vector<Step>,2> recurrent;std::array<std::shared_ptr<CudaGru>,2> cuda_recurrent; };
Matrix softmax(const Matrix& input) {
    auto output=cpu_softmax(input.data(),unsigned(input.rows()),unsigned(input.cols()));
    return Eigen::Map<const Matrix>(output.data(),input.rows(),input.cols());
}
Matrix activated(const Matrix& input,unsigned activation,ExecutionBackend backend=ExecutionBackend::scalar) {
    if(activation==1) return input.cwiseMax(0.f);
    if(activation==2) {
        if(backend==ExecutionBackend::cuda) {
            auto values=cuda_softmax(input.data(),unsigned(input.rows()),unsigned(input.cols()));
            return Eigen::Map<const Matrix>(values.data(),input.rows(),input.cols());
        }
        return softmax(input);
    }
    return input;
}
Matrix product(const Matrix& left,const Matrix& right,ExecutionBackend backend=ExecutionBackend::scalar,bool transpose_left=false,bool transpose_right=false) {
    Eigen::Index rows=transpose_left?left.cols():left.rows(),inner=transpose_left?left.rows():left.cols(),cols=transpose_right?right.rows():right.cols();
    if(backend==ExecutionBackend::cuda) {
        auto values=cuda_product(left.data(),right.data(),unsigned(rows),unsigned(inner),unsigned(cols),transpose_left,transpose_right);
        return Eigen::Map<const Matrix>(values.data(),rows,cols);
    }
    auto values=cpu_product(left.data(),right.data(),unsigned(rows),unsigned(inner),unsigned(cols),transpose_left,transpose_right);
    return Eigen::Map<const Matrix>(values.data(),rows,cols);
}
Matrix activation_gradient(const Matrix& gradient,const Matrix& output,unsigned activation,ExecutionBackend backend=ExecutionBackend::scalar) {
    if(activation==1) return (gradient.array()*(output.array()>0).cast<float>()).matrix();
    if(activation==2) {
        if(backend==ExecutionBackend::cuda) {
            auto values=cuda_softmax_gradient(gradient.data(),output.data(),unsigned(output.rows()),unsigned(output.cols()));
            return Eigen::Map<const Matrix>(values.data(),output.rows(),output.cols());
        }
        Matrix result=gradient;
        Matrix products=(gradient.array()*output.array()).matrix();
        auto sums=cpu_sum(products.data(),unsigned(products.rows()),unsigned(products.cols()),1);
        for(Eigen::Index row=0;row<gradient.rows();++row) {
            float sum=sums[row];
            result.row(row)=(output.row(row).array()*(gradient.row(row).array()-sum)).matrix();
        }
        return result;
    }
    return gradient;
}
}

struct Network::Impl {
    unsigned alphabet=0,context=0;std::vector<Node> nodes;std::vector<Value> values;
    std::vector<std::int32_t> contexts;unsigned batch=0;float beta1_power=.9f,beta2_power=.999f;bool optimizer_ready=false;
    TrainOptions optimizer_options;
    unsigned optimizer_steps=0;
    ExecutionBackend backend=ExecutionBackend::scalar;
    void forward(const std::vector<std::int32_t>& input,bool cache,ExecutionBackend execution=ExecutionBackend::scalar) {
        need(execution==ExecutionBackend::scalar || execution==ExecutionBackend::cuda,"unknown execution backend");
        if(execution==ExecutionBackend::scalar)
            need(__builtin_cpu_supports("avx"),"numerical profile 1 requires an AVX CPU");
        if(execution==ExecutionBackend::cuda) {
            need(cuda_training_compiled(),"CUDA training was not built");
            // This backend implements the official sigmoid bootstrap graph.
            // A CPU hard_sigmoid codec may never silently become a CuDNN model.
            need(nodes.size()==11,"CUDA backend requires the bootstrap training graph");
            for(const auto& node:nodes) if(node.kind==2) need(node.activation==1,"CUDA bootstrap requires sigmoid gates");
        }
        backend=execution;
        need(!input.empty() && input.size()%context==0,"contexts must contain complete windows");
        need(input.size()/context<=2048,"native batch limit exceeded");
        std::uint64_t elements=0;
        for(const auto& node:nodes) {
            elements+=std::uint64_t(node.steps)*node.features*(cache?2:1);
            // Scalar BPTT stores six host matrices for every recurrent tick;
            // CUDA keeps those intermediates in cuDNN's bounded reserve area.
            if(cache && node.kind==2 && execution==ExecutionBackend::scalar)
                elements+=2ull*context*(nodes[node.inputs[0]].features+5ull*node.features/2);
        }
        need(elements*(input.size()/context)*sizeof(float)<=1024ull*1024*1024,"network working memory limit exceeded; use microbatches for training");
        for(auto symbol:input) need(symbol>=0 && unsigned(symbol)<alphabet,"context symbol outside alphabet");
        contexts=input;batch=unsigned(input.size()/context);values.clear();values.resize(nodes.size());
        for(std::size_t index=0;index<nodes.size();++index) {
            auto& node=nodes[index];auto& out=values[index];
            if(node.kind==0) {
                out.data.resize(batch,context);
                for(unsigned row=0;row<input.size();++row) out.data.data()[row]=float(input[row]);
                continue;
            }
            auto& source=values[node.inputs[0]].data;
            if(node.kind==1) {
                out.data.resize(batch*context,node.features);
                for(unsigned row=0;row<input.size();++row) out.data.row(row)=node.tensors[0].weight.row(input[row]);
            } else if(node.kind==2) {
                unsigned units=node.features/2;out.data.resize(batch*context,node.features);
                if(backend==ExecutionBackend::cuda) {
                    for(unsigned direction=0;direction<2;++direction) {
                        auto executor=std::make_shared<CudaGru>(batch,context,unsigned(source.cols()),units,direction!=0,
                            std::array<const float*,3>{node.tensors[direction*3].weight.data(),node.tensors[direction*3+1].weight.data(),node.tensors[direction*3+2].weight.data()});
                        auto output=executor->forward(source.data());
                        out.data.middleCols(direction*units,units)=Eigen::Map<const Matrix>(output.data(),batch*context,units);
                        if(cache) out.cuda_recurrent[direction]=std::move(executor);
                    }
                    need(out.data.allFinite(),"nonfinite CUDA inference");continue;
                }
                for(unsigned direction=0;direction<2;++direction) {
                    const Matrix& kernel=node.tensors[direction*3].weight;
                    const Matrix& recurrent=node.tensors[direction*3+1].weight;
                    const Matrix& bias=node.tensors[direction*3+2].weight;
                    Matrix previous=Matrix::Zero(batch,units);
                    if(cache) out.recurrent[direction].reserve(context);
                    for(unsigned tick=0;tick<context;++tick) {
                        unsigned time=direction?context-1-tick:tick;Step step;
                        step.previous=previous;step.x.resize(batch,source.cols());
                        for(unsigned b=0;b<batch;++b) step.x.row(b)=source.row(b*context+time);
                        Matrix gates(batch,3*units),rec(batch,3*units);
                        for(unsigned gate=0;gate<3;++gate) {
                            gates.middleCols(gate*units,units)=product(step.x,kernel.middleCols(gate*units,units));
                            rec.middleCols(gate*units,units)=product(previous,recurrent.middleCols(gate*units,units));
                        }
                        gates.rowwise()+=bias.row(0);rec.rowwise()+=bias.row(1);
                        if(node.activation==1) {
                            step.z=(1.f/(1.f+(-(gates.leftCols(units)+rec.leftCols(units))).array().exp())).matrix();
                            step.r=(1.f/(1.f+(-(gates.middleCols(units,units)+rec.middleCols(units,units))).array().exp())).matrix();
                        } else {
                            step.z=((gates.leftCols(units)+rec.leftCols(units)).array()*.2f+.5f).min(1.f).max(0.f).matrix();
                            step.r=((gates.middleCols(units,units)+rec.middleCols(units,units)).array()*.2f+.5f).min(1.f).max(0.f).matrix();
                        }
                        step.recurrent=rec.rightCols(units);
                        Matrix candidate_input=(gates.rightCols(units).array()+step.r.array()*step.recurrent.array()).matrix();
                        // TF's CPU Eigen packets use this documented rational
                        // tanh approximation. Evaluate it scalarly, preserving
                        // the source's float32 operation order without SIMD.
                        step.candidate=candidate_input.unaryExpr([](float x){return Eigen::internal::generic_fast_tanh_float(x);});
                        previous=(step.z.array()*previous.array()+(1.f-step.z.array())*step.candidate.array()).matrix();
                        for(unsigned b=0;b<batch;++b) out.data.block(b*context+time,direction*units,1,units)=previous.row(b);
                        if(cache) out.recurrent[direction].push_back(std::move(step));
                    }
                }
            } else if(node.kind==3) {
                out.data.resize(batch*4,source.cols());
                for(unsigned b=0;b<batch;++b) for(unsigned time=0;time<4;++time) out.data.row(b*4+time)=source.row(b*context+15+16*time);
            } else if(node.kind==4) {
                out.data=Eigen::Map<const Matrix>(source.data(),batch,node.features);
            } else if(node.kind==5) {
                Matrix result(source.rows(),node.features);
                result=product(source,node.tensors[0].weight,backend);
                result.rowwise()+=node.tensors[1].weight.row(0);out.data=activated(result,node.activation,backend);
            } else if(node.kind==6) {
                out.data=source;
                for(std::size_t i=1;i<node.inputs.size();++i) out.data+=values[node.inputs[i]].data;
            } else if(node.kind==7) {
                out.data.resize(batch,node.features);unsigned col=0;
                for(auto parent:node.inputs) {auto& value=values[parent].data;out.data.middleCols(col,value.cols())=value;col+=unsigned(value.cols());}
            } else if(node.kind==8) out.data=activated(source,node.activation,backend);
            need(out.data.allFinite(),"nonfinite native inference");
        }
    }
    void backward(Matrix gradient) {
        Matrix flat_skip;
        for(std::size_t i=0;i<nodes.size();++i) {
            values[i].gradient=Matrix::Zero(values[i].data.rows(),values[i].data.cols());
            for(auto& tensor:nodes[i].tensors) tensor.gradient=Matrix::Zero(tensor.weight.rows(),tensor.weight.cols());
        }
        values.back().gradient=std::move(gradient);
        for(std::size_t position=nodes.size();position-- >1;) {
            // Grappler canonicalizes the source flat-backbone AddN inputs by
            // name: concatenate_1, dense_1, dense_5. Preserve its association.
            if(position==7 && flat_skip.size())values[position].gradient+=flat_skip;
            auto& node=nodes[position];auto& out=values[position];auto& parent=values[node.inputs[0]];
            if(node.kind==1) {
                if(backend==ExecutionBackend::cuda) {
                    auto result=cuda_embedding_gradient(out.gradient.data(),contexts.data(),unsigned(contexts.size()),node.features,alphabet,1.f);
                    node.tensors[0].gradient=Eigen::Map<const Matrix>(result.data(),alphabet,node.features);
                } else for(unsigned row=0;row<contexts.size();++row) node.tensors[0].gradient.row(contexts[row])+=out.gradient.row(row);
            } else if(node.kind==2) {
                unsigned units=node.features/2;
                if(backend==ExecutionBackend::cuda) {
                    for(unsigned direction=0;direction<2;++direction) {
                        Matrix gradient=out.gradient.middleCols(direction*units,units);
                        auto result=out.cuda_recurrent[direction]->backward(gradient.data());
                        parent.gradient+=Eigen::Map<const Matrix>(result.input.data(),parent.data.rows(),parent.data.cols());
                        auto& kernel=node.tensors[direction*3];auto& recurrent=node.tensors[direction*3+1];auto& bias=node.tensors[direction*3+2];
                        kernel.gradient=Eigen::Map<const Matrix>(result.kernel.data(),kernel.weight.rows(),kernel.weight.cols());
                        recurrent.gradient=Eigen::Map<const Matrix>(result.recurrent.data(),recurrent.weight.rows(),recurrent.weight.cols());
                        bias.gradient=Eigen::Map<const Matrix>(result.bias.data(),bias.weight.rows(),bias.weight.cols());
                    }
                    continue;
                }
                for(unsigned direction=0;direction<2;++direction) {
                    auto& kernel=node.tensors[direction*3];auto& recurrent=node.tensors[direction*3+1];auto& bias=node.tensors[direction*3+2];
                    Matrix carry=Matrix::Zero(batch,units);
                    for(unsigned reverse=context;reverse-- >0;) {
                        auto& step=out.recurrent[direction][reverse];unsigned time=direction?context-1-reverse:reverse;
                        Matrix dh=carry;
                        for(unsigned b=0;b<batch;++b) dh.row(b)+=out.gradient.block(b*context+time,direction*units,1,units);
                        Matrix dz=(dh.array()*step.previous.array()).matrix();
                        dz-= (dh.array()*step.candidate.array()).matrix();
                        Matrix candidate=(dh.array()*(1.f-step.z.array())*(1.f-step.candidate.array().square())).matrix();
                        Matrix dr=(candidate.array()*step.recurrent.array()).matrix();
                        if(node.activation==1) {
                            dz.array()*=step.z.array()*(1.f-step.z.array());
                            dr.array()*=step.r.array()*(1.f-step.r.array());
                        } else {
                            dz.array()*=((step.z.array()>0.f)&&(step.z.array()<1.f)).cast<float>()*.2f;
                            dr.array()*=((step.r.array()>0.f)&&(step.r.array()<1.f)).cast<float>()*.2f;
                        }
                        Matrix dx(batch,units*3),dhrec(batch,units*3);
                        dx<<dz,dr,candidate;dhrec<<dz,dr,(candidate.array()*step.r.array()).matrix();
                        // Source GRU implementation=1 slices its three kernels
                        // before MatMul. Its adjoints likewise multiply each
                        // gate separately, then concatenate the kernel gradient.
                        for(unsigned gate=0;gate<3;++gate) {
                            kernel.gradient.middleCols(gate*units,units)+=product(step.x,dx.middleCols(gate*units,units),backend,true,false);
                            recurrent.gradient.middleCols(gate*units,units)+=product(step.previous,dhrec.middleCols(gate*units,units),backend,true,false);
                        }
                        auto input_sums=cpu_sum(dx.data(),batch,3*units,0);
                        auto recurrent_sums=cpu_sum(dhrec.data(),batch,3*units,0);
                        bias.gradient.row(0)+=Eigen::Map<const Matrix>(input_sums.data(),1,3*units);
                        bias.gradient.row(1)+=Eigen::Map<const Matrix>(recurrent_sums.data(),1,3*units);
                        Matrix input_gradient=Matrix::Zero(batch,step.x.cols());
                        // Optimized AddN sorts MatMul_1_grad, MatMul_2_grad,
                        // MatMul_grad by name: reset, candidate, update.
                        for(unsigned gate:{1u,2u,0u})
                            input_gradient+=product(dx.middleCols(gate*units,units),kernel.weight.middleCols(gate*units,units).transpose());
                        for(unsigned b=0;b<batch;++b) parent.gradient.row(b*context+time)+=input_gradient.row(b);
                        carry=Matrix::Zero(batch,units);
                        for(unsigned gate=0;gate<3;++gate)
                            carry+=product(dhrec.middleCols(gate*units,units),recurrent.weight.middleCols(gate*units,units).transpose());
                        carry+=(dh.array()*step.z.array()).matrix();
                    }
                }
            } else if(node.kind==3) {
                for(unsigned b=0;b<batch;++b) for(unsigned time=0;time<4;++time) parent.gradient.row(b*context+15+16*time)+=out.gradient.row(b*4+time);
            } else if(node.kind==4) {
                parent.gradient+=Eigen::Map<const Matrix>(out.gradient.data(),parent.data.rows(),parent.data.cols());
            } else if(node.kind==5) {
                auto local=activation_gradient(out.gradient,out.data,node.activation,backend);
                node.tensors[0].gradient+=product(parent.data,local,backend,true,false);
                if(backend==ExecutionBackend::cuda) {
                    auto sums=cuda_sum(local.data(),unsigned(local.rows()),unsigned(local.cols()),0);
                    node.tensors[1].gradient.row(0)+=Eigen::Map<const Matrix>(sums.data(),1,local.cols());
                } else {
                    auto sums=cpu_sum(local.data(),unsigned(local.rows()),unsigned(local.cols()),0);
                    node.tensors[1].gradient.row(0)+=Eigen::Map<const Matrix>(sums.data(),1,local.cols());
                }
                auto input_gradient=product(local,node.tensors[0].weight,backend,false,true);
                if(nodes.size()==32 && position==24)flat_skip=std::move(input_gradient);
                else parent.gradient+=input_gradient;
            } else if(node.kind==6) {
                for(auto input:node.inputs) values[input].gradient+=out.gradient;
            } else if(node.kind==7) {
                unsigned col=0;
                for(auto input:node.inputs) {auto& value=values[input];value.gradient+=out.gradient.middleCols(col,value.data.cols());col+=unsigned(value.data.cols());}
            } else if(node.kind==8) parent.gradient+=activation_gradient(out.gradient,out.data,node.activation,backend);
        }
    }
    float differentiate(const std::vector<std::int32_t>& input,const std::vector<std::int32_t>& labels,ExecutionBackend execution=ExecutionBackend::scalar) {
        need(!input.empty() && input.size()%64==0 && labels.size()==input.size()/64,"training batch dimensions invalid");
        for(auto label:labels) need(label>=0 && unsigned(label)<alphabet,"training label outside alphabet");
        forward(input,true,execution);auto& output=values.back().data;
        Matrix derivative=Matrix::Zero(output.rows(),output.cols());float loss=0;
        // The source multiplies by a float32 cast of 1/np.log(2), then
        // K.mean contributes the batch divisor to the upstream gradient.
        float scale=float(1.0/std::log(2.0))/float(labels.size());
        std::vector<float> totals;
        if(execution==ExecutionBackend::cuda)totals=cuda_sum(output.data(),unsigned(output.rows()),unsigned(output.cols()),1);
        else totals=cpu_sum(output.data(),unsigned(output.rows()),unsigned(output.cols()),1);
        for(unsigned row=0;row<labels.size();++row) {
            float total=totals.empty()?output.row(row).sum():totals[row],probability=output(row,labels[row])/total;
            float clipped=std::max(1e-7f,std::min(1.f-1e-7f,probability));loss-=std::log(clipped)*scale;
            if(probability>1e-7f && probability<1.f-1e-7f) {
                // Match TF Div's two gradient operations, including float32
                // rounding, rather than canceling normalization algebraically.
                // Locked TF 1.14 has a fixed 2019-11-01 compatibility horizon;
                // its LogGrad uses grad * reciprocal(x), not direct division.
                float upstream=-scale*(1.f/probability);
                float direct=upstream/total;
                // TF 1.14 RealDivGrad evaluates grad * ((-x / y) / y).
                // Reassociating this to (grad / y) * (-x / y) changes tiny
                // residual gradients that Adam can amplify into weight errors.
                float normalization=upstream*((-output(row,labels[row])/total)/total);
                derivative.row(row).setConstant(normalization);derivative(row,labels[row])+=direct;
            }
        }
        backward(std::move(derivative));return loss;
    }
};

Network::Network(std::unique_ptr<Impl> impl):impl_(std::move(impl)) {}
Network::~Network()=default;
Network::Network(Network&&) noexcept=default;
Network& Network::operator=(Network&&) noexcept=default;
Network::Network(const Network& other):impl_(std::make_unique<Impl>(*other.impl_)) {}
Network& Network::operator=(const Network& other) { if(this!=&other) impl_=std::make_unique<Impl>(*other.impl_);return *this; }
unsigned Network::alphabet() const {return impl_->alphabet;}
unsigned Network::context() const {return impl_->context;}

Network Network::load(const Bytes& bytes,std::size_t max_bytes) {
    need(bytes.size()<=max_bytes && bytes.size()<=512u*1024u*1024u && bytes.size()>=20,"model byte limit or header invalid");
    need(std::equal(bytes.begin(),bytes.begin()+8,"DZIPNN01"),"unknown native model version");
    Reader reader{bytes,8};auto impl=std::make_unique<Impl>();
    impl->context=reader.word();impl->alphabet=reader.word();unsigned count=reader.word();
    need(impl->context==64 && impl->alphabet>=1 && impl->alphabet<=256 && impl->alphabet!=9,"unsupported source neural profile");
    need(count>=2 && count<=64,"invalid node count");
    for(unsigned index=0;index<count;++index) {
        Node node;node.kind=reader.word();node.activation=reader.word();unsigned inputs=reader.word();
        need(node.kind<=8 && node.activation<=2 && inputs<=4,"invalid node descriptor");
        for(unsigned i=0;i<inputs;++i) {auto parent=reader.word();need(parent<index,"model graph is not ordered");node.inputs.push_back(parent);}
        need(index?inputs>0 && node.kind>0:inputs==0 && node.kind==0,"invalid source graph input");
        need(node.kind==6 || node.kind==7 || inputs==(index?1u:0u),"invalid unary node inputs");
        need(node.kind==2?node.activation<=1:(node.kind==5 || node.kind==8 || node.activation==0),"invalid node activation");
        unsigned tensors=reader.word();need(tensors<=6,"too many node weights");
        for(unsigned i=0;i<tensors;++i) {
            Tensor tensor;unsigned rank=reader.word();need(rank>=1 && rank<=2,"unsupported tensor rank");
            std::size_t elements=1;
            for(unsigned dim=0;dim<rank;++dim) {unsigned size=reader.word();need(size && size<=4096,"tensor dimension too large");elements*=size;tensor.shape.push_back(size);}
            need(elements<=(bytes.size()-reader.pos)/4,"truncated tensor data");
            tensor.weight.resize(rank==1?1:tensor.shape[0],tensor.shape.back());
            for(std::size_t k=0;k<elements;++k) tensor.weight.data()[k]=reader.real();
            node.tensors.push_back(std::move(tensor));
        }
        const Node* parent=inputs?&impl->nodes[node.inputs[0]]:nullptr;
        if(node.kind==0) {node.steps=64;node.features=1;need(tensors==0,"input weights invalid");}
        else if(node.kind==1) {
            need(parent->kind==0 && tensors==1 && node.tensors[0].shape.size()==2 && node.tensors[0].shape[0]==impl->alphabet,"invalid embedding shape");
            node.steps=64;node.features=node.tensors[0].shape[1];need(node.features<=32,"embedding too wide");
        } else if(node.kind==2) {
            need(tensors==6 && parent->steps==64,"invalid recurrent shape");unsigned units=unsigned(node.tensors[1].weight.rows());need(units<=128,"GRU too wide");
            for(unsigned d=0;d<2;++d) {
                need(node.tensors[3*d].shape==std::vector<unsigned>({parent->features,3*units}) &&
                     node.tensors[3*d+1].shape==std::vector<unsigned>({units,3*units}) &&
                     node.tensors[3*d+2].shape==std::vector<unsigned>({2,3*units}),"GRU weight dimensions mismatch");
            }
            node.steps=64;node.features=2*units;
        } else if(node.kind==3) {need(tensors==0 && parent->kind==2 && parent->steps==64,"invalid selected-time layer");node.steps=4;node.features=parent->features;}
        else if(node.kind==4) {need(tensors==0,"flatten has weights");node.steps=1;node.features=parent->steps*parent->features;}
        else if(node.kind==5) {
            need(parent->steps==1 && tensors==2 && node.tensors[0].shape.size()==2 && node.tensors[1].shape.size()==1,"invalid dense descriptor");
            node.features=node.tensors[1].shape[0];node.steps=1;
            need(node.tensors[0].shape==std::vector<unsigned>({parent->features,node.features}),"dense weight dimensions mismatch");
        } else if(node.kind==6 || node.kind==7) {
            need(tensors==0 && inputs>=2,"invalid merge layer");node.steps=parent->steps;node.features=node.kind==6?parent->features:0;
            for(auto input:node.inputs) {
                auto& p=impl->nodes[input];need(p.steps==node.steps,"merge steps mismatch");
                if(node.kind==6) need(p.features==node.features,"add dimensions mismatch");else node.features+=p.features;
            }
            if(node.kind==7) need(node.steps==1,"sequence concatenation unsupported");
        } else {need(tensors==0,"activation has weights");node.steps=parent->steps;node.features=parent->features;}
        need(node.features<=8192,"graph width too large");impl->nodes.push_back(std::move(node));
    }
    need(reader.pos==bytes.size(),"trailing model bytes");
    auto& last=impl->nodes.back();need(last.steps==1 && last.features==impl->alphabet && last.activation==2,"model must end in alphabet softmax");
    return Network(std::move(impl));
}

Network Network::create(unsigned alphabet,ModelProfile profile,std::uint32_t seed) {
    need(alphabet>=1 && alphabet<=256 && alphabet!=9,"unsupported source alphabet");
    need(profile==ModelProfile::bootstrap_cpu || profile==ModelProfile::combined_cpu ||
         profile==ModelProfile::bootstrap_training,"unknown model profile");
    auto impl=std::make_unique<Impl>();impl->alphabet=alphabet;impl->context=64;
    std::mt19937 random(seed);
    auto uniform=[&](){return (float(random()>>8)+.5f)*(1.f/16777216.f);};
    auto tensor=[&](unsigned rows,unsigned cols,float extent,bool vector=false) {
        Tensor value;value.shape=vector?std::vector<unsigned>{cols}:std::vector<unsigned>{rows,cols};
        value.weight.resize(rows,cols);
        for(Eigen::Index i=0;i<value.weight.size();++i) value.weight.data()[i]=extent*(2.f*uniform()-1.f);
        return value;
    };
    auto append=[&](unsigned kind,unsigned activation,std::vector<unsigned> inputs,unsigned steps,unsigned features,std::vector<Tensor> tensors={}) {
        Node node;node.kind=kind;node.activation=activation;node.inputs=std::move(inputs);
        node.steps=steps;node.features=features;node.tensors=std::move(tensors);
        impl->nodes.push_back(std::move(node));return unsigned(impl->nodes.size()-1);
    };
    auto dense=[&](unsigned parent,unsigned width,unsigned activation=0) {
        unsigned input=impl->nodes[parent].features;
        return append(5,activation,{parent},1,width,{tensor(input,width,std::sqrt(6.f/float(input+width))),tensor(1,width,0,true)});
    };
    unsigned input=append(0,0,{},64,1);
    unsigned embedding=alphabet<10?8:16,units=alphabet<4?8:(alphabet<10?32:128);
    unsigned hidden=alphabet<10?16:(alphabet<128?128:256);
    unsigned recurrent=append(1,0,{input},64,embedding,{tensor(alphabet,embedding,.05f)});
    for(unsigned layer=0;layer<2;++layer) {
        std::vector<Tensor> weights;
        unsigned features=impl->nodes[recurrent].features;
        for(unsigned direction=0;direction<2;++direction) {
            weights.push_back(tensor(features,3*units,std::sqrt(6.f/float(features+3*units))));
            // Deterministic native orthogonal row initializer, distinct from TF's
            // initializer. Float weights and full seed state are serialized.
            auto orthogonal=tensor(units,3*units,1);
            for(unsigned row=0;row<units;++row) {
                for(unsigned prior=0;prior<row;++prior) {
                    double dot=0;for(unsigned col=0;col<3*units;++col) dot+=double(orthogonal.weight(row,col))*orthogonal.weight(prior,col);
                    for(unsigned col=0;col<3*units;++col) orthogonal.weight(row,col)-=float(dot)*orthogonal.weight(prior,col);
                }
                double squared=0;for(unsigned col=0;col<3*units;++col) squared+=double(orthogonal.weight(row,col))*orthogonal.weight(row,col);
                need(squared>0,"degenerate orthogonal initializer");
                orthogonal.weight.row(row)/=float(std::sqrt(squared));
            }
            weights.push_back(std::move(orthogonal));weights.push_back(tensor(2,3*units,0));
        }
        recurrent=append(2,profile==ModelProfile::bootstrap_training?1:0,{recurrent},64,2*units,std::move(weights));
    }
    auto selected=append(3,0,{recurrent},4,2*units);
    auto flat=append(4,0,{selected},1,8*units);
    auto prelogits=dense(flat,hidden,1);
    auto logits1=dense(prelogits,alphabet),logits2=dense(flat,alphabet);
    auto logits=append(6,0,{logits1,logits2},1,alphabet);
    if(profile==ModelProfile::combined_cpu) {
        unsigned support_width=alphabet<10?16:32,wide=alphabet<10?1024:2048;
        auto support=append(1,0,{input},64,support_width,{tensor(alphabet,support_width,.05f)});
        auto support_flat=append(4,0,{support},1,64*support_width);
        auto joined=append(7,0,{support_flat,flat},1,64*support_width+8*units);
        auto residual=dense(joined,wide,1);
        for(unsigned block=0;block<2;++block) {
            auto first=append(8,1,{residual},1,wide);first=dense(first,wide);
            auto second=append(8,1,{first},1,wide);second=dense(second,wide);
            residual=append(6,0,{second,residual},1,wide);
        }
        auto e=dense(joined,wide,1);e=dense(e,wide,1);
        auto direct=dense(joined,alphabet),branch=dense(residual,alphabet),other=dense(e,alphabet);
        auto merged=append(7,0,{direct,branch,other,logits},1,4*alphabet);
        logits=dense(merged,alphabet);
    }
    append(8,2,{logits},1,alphabet);
    auto result=Network(std::move(impl));return load(result.serialize());
}

void Network::import_bootstrap(const Network& bootstrap) {
    need(impl_->alphabet==bootstrap.impl_->alphabet,"bootstrap alphabet differs");
    // Shared source tensors: embedding, both BiGRUs and prelogits Dense.
    for(unsigned index:{1u,2u,3u,6u}) {
        need(impl_->nodes.size()>index && bootstrap.impl_->nodes.size()>index,"bootstrap graph missing layers");
        auto& destination=impl_->nodes[index];const auto& source=bootstrap.impl_->nodes[index];
        need(destination.kind==source.kind && destination.tensors.size()==source.tensors.size(),"bootstrap layer mismatch");
        for(unsigned t=0;t<source.tensors.size();++t) {
            need(destination.tensors[t].shape==source.tensors[t].shape,"bootstrap tensor mismatch");
            destination.tensors[t].weight=source.tensors[t].weight;
        }
    }
    reset_optimizer();
}

Network Network::cpu_bootstrap() const {
    need(impl_->nodes.size()==11,"CPU bootstrap conversion requires the source bootstrap graph");
    auto result=*this;
    for(auto& node:result.impl_->nodes) if(node.kind==2) node.activation=0;
    result.reset_optimizer();return result;
}

Bytes Network::serialize() const {
    Bytes bytes{'D','Z','I','P','N','N','0','1'};word(bytes,impl_->context);word(bytes,impl_->alphabet);word(bytes,unsigned(impl_->nodes.size()));
    for(const auto& node:impl_->nodes) {
        word(bytes,node.kind);word(bytes,node.activation);word(bytes,unsigned(node.inputs.size()));
        for(auto input:node.inputs) word(bytes,input);
        word(bytes,unsigned(node.tensors.size()));
        for(const auto& tensor:node.tensors) {
            word(bytes,unsigned(tensor.shape.size()));for(auto dim:tensor.shape) word(bytes,dim);
            for(Eigen::Index i=0;i<tensor.weight.size();++i) {unsigned bits;float value=tensor.weight.data()[i];std::memcpy(&bits,&value,4);word(bytes,bits);}
        }
    }
    return bytes;
}
bool Network::cuda_compiled() noexcept {return cuda_training_compiled();}
std::vector<float> Network::predict(const std::vector<std::int32_t>& input,ExecutionBackend backend) {
    auto guard=cuda_call_guard(backend);
    impl_->forward(input,false,backend);auto& result=impl_->values.back().data;
    return {result.data(),result.data()+result.size()};
}
void Network::reset_optimizer() {
    for(auto& node:impl_->nodes) for(auto& tensor:node.tensors) {tensor.m.resize(0,0);tensor.v.resize(0,0);}
    impl_->optimizer_ready=false;
    impl_->optimizer_steps=0;
}
Bytes Network::gradient_graph(const std::vector<std::int32_t>& input,const std::vector<std::int32_t>& labels,ExecutionBackend backend) {
    auto guard=cuda_call_guard(backend);
    impl_->differentiate(input,labels,backend);
    for(const auto& node:impl_->nodes) for(const auto& tensor:node.tensors)
        need(tensor.gradient.allFinite(),"nonfinite gradient diagnostic");
    auto swap=[&](){for(auto& node:impl_->nodes)for(auto& tensor:node.tensors)tensor.weight.swap(tensor.gradient);};
    swap();
    try {auto bytes=serialize();swap();return bytes;}
    catch(...) {swap();throw;}
}
float Network::train(const std::vector<std::int32_t>& input,const std::vector<std::int32_t>& labels,const TrainOptions& options) {
    auto guard=cuda_call_guard(options.backend);
    need(!input.empty() && input.size()%64==0 && labels.size()==input.size()/64,"training batch dimensions invalid");
    need(std::isfinite(options.learning_rate) && options.learning_rate>0 &&
         std::isfinite(options.beta1) && options.beta1>=0 && options.beta1<1 &&
         std::isfinite(options.beta2) && options.beta2>=0 && options.beta2<1 &&
         std::isfinite(options.epsilon) && options.epsilon>0 &&
         std::isfinite(options.clipnorm) && options.clipnorm>=0,"invalid Adam options");
    if(impl_->optimizer_ready) {
        const auto& prior=impl_->optimizer_options;
        need(options.learning_rate==prior.learning_rate && options.beta1==prior.beta1 &&
             options.beta2==prior.beta2 && options.epsilon==prior.epsilon && options.clipnorm==prior.clipnorm && options.backend==prior.backend,
             "Adam options changed; reset optimizer first");
    }
    need(labels.size()<=2048 && options.microbatch<=2048,"training batch exceeds limit");
    float loss=0;
    // Keras clips IndexedSlices before their duplicate embedding indices are
    // densified by Adam. Clipping an already summed row changes float rounding.
    std::vector<Matrix> sparse_gradients(impl_->nodes.size());
    auto retain_sparse=[&](std::size_t first,std::size_t end,float proportion) {
        if(options.rule!=AdamRule::keras || options.clipnorm==0)return;
        for(unsigned i=0;i<impl_->nodes.size();++i)if(impl_->nodes[i].kind==1) {
            auto& target=sparse_gradients[i];const auto& gradient=impl_->values[i].gradient;
            if(!target.size())target.resize(input.size(),gradient.cols());
            target.middleRows(first*64,(end-first)*64)=gradient*proportion;
        }
    };
    if(options.microbatch && labels.size()>options.microbatch) {
        std::vector<std::vector<Matrix>> accumulated;
        for(const auto& node:impl_->nodes) {
            std::vector<Matrix> row;for(const auto& tensor:node.tensors) row.push_back(Matrix::Zero(tensor.weight.rows(),tensor.weight.cols()));
            accumulated.push_back(std::move(row));
        }
        for(std::size_t first=0;first<labels.size();first+=options.microbatch) {
            auto end=std::min(labels.size(),first+options.microbatch);
            std::vector<std::int32_t> chunk(input.begin()+std::ptrdiff_t(first*64),input.begin()+std::ptrdiff_t(end*64));
            std::vector<std::int32_t> targets(labels.begin()+std::ptrdiff_t(first),labels.begin()+std::ptrdiff_t(end));
            float proportion=float(end-first)/float(labels.size());loss+=impl_->differentiate(chunk,targets,options.backend)*proportion;
            retain_sparse(first,end,proportion);
            for(unsigned i=0;i<impl_->nodes.size();++i) for(unsigned t=0;t<impl_->nodes[i].tensors.size();++t)
                accumulated[i][t]+=impl_->nodes[i].tensors[t].gradient*proportion;
        }
        for(unsigned i=0;i<impl_->nodes.size();++i) for(unsigned t=0;t<impl_->nodes[i].tensors.size();++t)
            impl_->nodes[i].tensors[t].gradient=std::move(accumulated[i][t]);
    } else {loss=impl_->differentiate(input,labels,options.backend);retain_sparse(0,labels.size(),1.f);}
    if(!impl_->optimizer_ready) {
        impl_->beta1_power=options.beta1;impl_->beta2_power=options.beta2;
        impl_->optimizer_options=options;impl_->optimizer_ready=true;
    }
    need(options.rule==AdamRule::tensorflow || options.rule==AdamRule::keras,"unknown Adam rule");
    need(options.rule==impl_->optimizer_options.rule,"Adam rule changed; reset optimizer first");
    ++impl_->optimizer_steps;
    if(options.rule==AdamRule::keras) {
        if(options.backend==ExecutionBackend::cuda) {
            auto powers=cuda_adam_powers(options.beta1,options.beta2,impl_->optimizer_steps);
            impl_->beta1_power=powers[0];impl_->beta2_power=powers[1];
        } else {
            impl_->beta1_power=std::pow(options.beta1,float(impl_->optimizer_steps));
            impl_->beta2_power=std::pow(options.beta2,float(impl_->optimizer_steps));
        }
    }
    float learning_rate=options.rule==AdamRule::keras?
        options.learning_rate*(std::sqrt(1.f-impl_->beta2_power)/(1.f-impl_->beta1_power)):
        options.learning_rate*std::sqrt(1.f-impl_->beta2_power)/(1.f-impl_->beta1_power);
    float norm=0;
    // K.square converts IndexedSlices to a dense tensor for the norm, even
    // though clip_norm subsequently clips their individual values sparsely.
    if(options.clipnorm>0) for(auto& node:impl_->nodes) for(auto& tensor:node.tensors)
        norm+=options.backend==ExecutionBackend::cuda?
            cuda_sum(tensor.gradient.data(),unsigned(tensor.gradient.rows()),unsigned(tensor.gradient.cols()),2,true)[0]:
            tensor.gradient.squaredNorm();
    norm=std::sqrt(norm);
    float clipping=options.clipnorm>0 && norm>options.clipnorm?options.clipnorm/norm:1.f;
    for(unsigned node_index=0;node_index<impl_->nodes.size();++node_index)for(auto& tensor:impl_->nodes[node_index].tensors) {
        need(tensor.gradient.allFinite(),"nonfinite training gradient");
        if(!tensor.m.size()) {tensor.m=Matrix::Zero(tensor.weight.rows(),tensor.weight.cols());tensor.v=tensor.m;}
        if(sparse_gradients[node_index].size()) {
            auto& slices=sparse_gradients[node_index];
            if(options.backend==ExecutionBackend::cuda) {
                auto result=cuda_embedding_gradient(slices.data(),input.data(),unsigned(input.size()),unsigned(slices.cols()),impl_->alphabet,clipping);
                tensor.gradient=Eigen::Map<const Matrix>(result.data(),impl_->alphabet,slices.cols());
            } else {
                tensor.gradient.setZero();slices*=clipping;
                for(unsigned row=0;row<input.size();++row)tensor.gradient.row(input[row])+=slices.row(row);
            }
        } else tensor.gradient*=clipping;
        if(options.rule==AdamRule::tensorflow && options.backend==ExecutionBackend::scalar) {
            cpu_adam(tensor.weight.data(),tensor.m.data(),tensor.v.data(),tensor.gradient.data(),std::size_t(tensor.weight.size()),
                     options.beta1,options.beta2,learning_rate,options.epsilon,impl_->nodes[node_index].kind==1);
            need(tensor.weight.allFinite(),"nonfinite updated weight");continue;
        }
        if(options.rule==AdamRule::keras) {
            tensor.m.array()=options.beta1*tensor.m.array()+(1.f-options.beta1)*tensor.gradient.array();
            tensor.v.array()=options.beta2*tensor.v.array()+(1.f-options.beta2)*tensor.gradient.array().square();
        } else {
            tensor.m.array()+= (tensor.gradient.array()-tensor.m.array())*(1.f-options.beta1);
            tensor.v.array()+= (tensor.gradient.array().square()-tensor.v.array())*(1.f-options.beta2);
        }
        tensor.weight.array()-= learning_rate*tensor.m.array()/(tensor.v.array().sqrt()+options.epsilon);
        need(tensor.weight.allFinite(),"nonfinite updated weight");
    }
    impl_->beta1_power*=options.beta1;impl_->beta2_power*=options.beta2;
    return loss;
}
Bytes Network::trace_graph(const std::vector<std::int32_t>& input,const std::vector<std::int32_t>& labels,ExecutionBackend backend) {
    auto guard=cuda_call_guard(backend);
    impl_->differentiate(input,labels,backend);
    Bytes bytes{'D','Z','I','P','T','R','0','1'};word(bytes,unsigned(impl_->values.size()));
    for(const auto& value:impl_->values) {
        word(bytes,unsigned(value.data.rows()));word(bytes,unsigned(value.data.cols()));
        for(const auto* array:{&value.data,&value.gradient})for(Eigen::Index i=0;i<array->size();++i) {
            unsigned bits;float real=array->data()[i];std::memcpy(&bits,&real,4);word(bytes,bits);
        }
    }
    return bytes;
}
}  // namespace dzip
