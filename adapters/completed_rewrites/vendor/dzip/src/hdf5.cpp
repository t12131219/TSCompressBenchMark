#include "dzip_nn.hpp"
#include <hdf5.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <stdexcept>

namespace dzip {
namespace {
void need(bool ok,const char* message) {if(!ok) throw std::invalid_argument(message);}
struct Handle {
    hid_t id;herr_t(*close)(hid_t);
    Handle(hid_t value,herr_t(*closer)(hid_t)):id(value),close(closer) {need(id>=0,"HDF5 object open failed");}
    ~Handle(){close(id);}
    Handle(const Handle&)=delete;
    operator hid_t() const {return id;}
};
void hard_path(hid_t group,const std::string& name) {
    need(!name.empty() && name.front()!='/' && name.size()<=1024,"invalid checkpoint name");
    std::size_t start=0;
    for(std::size_t end=0;end<=name.size();++end) if(end==name.size() || name[end]=='/') {
        auto component=name.substr(start,end-start);
        need(!component.empty() && component!="." && component!="..","invalid checkpoint path component");
        auto prefix=name.substr(0,end);H5L_info_t info{};
        need(H5Lget_info(group,prefix.c_str(),&info,H5P_DEFAULT)>=0 && info.type==H5L_TYPE_HARD,"nonlocal checkpoint link");
        start=end+1;
    }
}
std::vector<std::string> names(hid_t group,const char* attribute) {
    Handle attr(H5Aopen(group,attribute,H5P_DEFAULT),H5Aclose);
    Handle type(H5Aget_type(attr),H5Tclose),space(H5Aget_space(attr),H5Sclose);
    auto count=H5Sget_simple_extent_npoints(space);need(count>=0 && count<=64,"checkpoint attribute too large");
    if(!count) return {};
    auto width=H5Tget_size(type);
    need(H5Tget_class(type)==H5T_STRING && H5Tis_variable_str(type)==0 && width>0 && width<=1024,"unsupported checkpoint name representation");
    std::vector<char> bytes(std::size_t(count)*width);
    need(H5Aread(attr,type,bytes.data())>=0,"checkpoint names unreadable");
    std::vector<std::string> result;
    for(hssize_t i=0;i<count;++i) {
        auto begin=bytes.begin()+std::ptrdiff_t(i*width);
        auto end=std::find(begin,begin+std::ptrdiff_t(width),'\0');result.emplace_back(begin,end);
    }
    return result;
}
struct Weight {std::vector<unsigned> shape;std::vector<float> data;};
Weight weight(hid_t group,const std::string& name,std::size_t& total) {
    hard_path(group,name);
    Handle dataset(H5Dopen2(group,name.c_str(),H5P_DEFAULT),H5Dclose);
    Handle type(H5Dget_type(dataset),H5Tclose),space(H5Dget_space(dataset),H5Sclose);
    Handle properties(H5Dget_create_plist(dataset),H5Pclose);
    need(H5Pget_nfilters(properties)==0 && H5Pget_external_count(properties)==0 && H5Pget_layout(properties)==H5D_CONTIGUOUS,"nonlocal or filtered checkpoint tensor");
    int rank=H5Sget_simple_extent_ndims(space);hsize_t dims[2]={};
    need(rank>=1 && rank<=2 && H5Tget_class(type)==H5T_FLOAT && H5Tget_size(type)==4,"unsupported checkpoint tensor");
    need(H5Sget_simple_extent_dims(space,dims,nullptr)>=0,"unreadable checkpoint shape");
    Weight result;std::size_t n=1;
    for(int i=0;i<rank;++i) {need(dims[i]>0 && dims[i]<=4096,"checkpoint dimension too large");n*=std::size_t(dims[i]);result.shape.push_back(unsigned(dims[i]));}
    need(n<=(512u*1024u*1024u-total)/4,"checkpoint weights exceed limit");total+=n*4;
    result.data.resize(n);need(H5Dread(dataset,H5T_NATIVE_FLOAT,H5S_ALL,H5S_ALL,H5P_DEFAULT,result.data.data())>=0,"checkpoint tensor unreadable");
    for(float value:result.data) need(std::isfinite(value),"nonfinite checkpoint weight");
    return result;
}
void convert_cudnn(std::vector<Weight>& weights,unsigned offset) {
    unsigned units=weights[offset+1].shape[0],input=weights[offset].shape[0];
    need(weights[offset+2].shape==std::vector<unsigned>{6*units},"unsupported recurrent checkpoint bias");
    for(unsigned item=0;item<2;++item) {
        auto& kernel=weights[offset+item];auto original=kernel.data;unsigned rows=item?units:input;
        need(kernel.shape==std::vector<unsigned>({rows,3*units}),"invalid CuDNN kernel shape");
        for(unsigned gate=0;gate<3;++gate) for(unsigned r=0;r<rows;++r) for(unsigned c=0;c<units;++c) {
            unsigned source_row=item?c:(r+c*rows)/units,source_col=item?r:(r+c*rows)%units;
            kernel.data[r*3*units+gate*units+c]=original[source_row*3*units+gate*units+source_col];
        }
    }
    weights[offset+2].shape={2,3*units};
}
unsigned get(const Bytes& bytes,std::size_t& pos) {
    need(bytes.size()-pos>=4,"invalid template graph");unsigned value=0;
    for(unsigned i=0;i<4;++i) value|=unsigned(bytes[pos++])<<(8*i);
    return value;
}
}
Network Network::from_hdf5(const std::string& path,ModelProfile profile,std::uint32_t seed) {
    static std::mutex hdf5_mutex;std::lock_guard<std::mutex> lock(hdf5_mutex);
    std::error_code error;auto size=std::filesystem::file_size(path,error);
    need(!error && size<=512u*1024u*1024u,"checkpoint file size invalid");
    Handle file(H5Fopen(path.c_str(),H5F_ACC_RDONLY,H5P_DEFAULT),H5Fclose);
    bool nested=H5Aexists(file,"layer_names")<=0;
    if(nested) hard_path(file,"model_weights");
    Handle root(H5Gopen2(file,nested?"model_weights":"/",H5P_DEFAULT),H5Gclose);
    auto layers=names(root,"layer_names");need(layers.size()==11,"not a source bootstrap checkpoint");
    std::vector<std::vector<Weight>> weights;std::size_t total=0;
    for(const auto& layer:layers) {
        hard_path(root,layer);Handle group(H5Gopen2(root,layer.c_str(),H5P_DEFAULT),H5Gclose);
        std::vector<Weight> tensors;for(const auto& name:names(group,"weight_names")) tensors.push_back(weight(group,name,total));
        weights.push_back(std::move(tensors));
    }
    need(weights[1].size()==1 && weights[1][0].shape.size()==2,"missing bootstrap embedding");
    unsigned alphabet=weights[1][0].shape[0];
    for(unsigned layer:{2u,3u}) {
        need(weights[layer].size()==6,"missing bidirectional checkpoint weights");
        for(unsigned direction:{0u,3u}) {
            need(weights[layer][direction+1].shape.size()==2,"invalid recurrent tensor rank");
            if(weights[layer][direction+2].shape.size()==1) convert_cudnn(weights[layer],direction);
        }
    }
    auto bootstrap=create(alphabet,profile==ModelProfile::bootstrap_training?profile:ModelProfile::bootstrap_cpu,seed);
    auto graph=bootstrap.serialize();std::size_t pos=8;get(graph,pos);get(graph,pos);unsigned count=get(graph,pos);
    need(count==weights.size(),"checkpoint layer count mismatch");
    for(unsigned layer=0;layer<count;++layer) {
        get(graph,pos);get(graph,pos);unsigned inputs=get(graph,pos);for(unsigned i=0;i<inputs;++i)get(graph,pos);
        unsigned tensors=get(graph,pos);need(tensors==weights[layer].size(),"checkpoint tensor count mismatch");
        for(unsigned t=0;t<tensors;++t) {
            unsigned rank=get(graph,pos);std::vector<unsigned> dims;
            for(unsigned d=0;d<rank;++d) dims.push_back(get(graph,pos));
            const auto& source=weights[layer][t];need(dims==source.shape,"checkpoint tensor shape mismatch");
            for(float value:source.data) {
                unsigned bits;std::memcpy(&bits,&value,4);
                for(unsigned b=0;b<4;++b) graph[pos++]=std::uint8_t(bits>>(8*b));
            }
        }
    }
    bootstrap=load(graph);
    if(profile==ModelProfile::combined_cpu) {auto combined=create(alphabet,profile,seed);combined.import_bootstrap(bootstrap);return combined;}
    return bootstrap;
}
}
