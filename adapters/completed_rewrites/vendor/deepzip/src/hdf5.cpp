#include "internal.hpp"
#include <hdf5.h>

namespace deepzip {
namespace {
class Handle {
public:
    Handle(hid_t id,herr_t(*closer)(hid_t)):id_(id),closer_(closer) {
        require(id>=0,Status::invalid_model,"HDF5 object open failed");
    }
    ~Handle(){closer_(id_);}
    Handle(const Handle&)=delete;
    Handle& operator=(const Handle&)=delete;
    operator hid_t() const{return id_;}
private:
    hid_t id_;
    herr_t(*closer_)(hid_t);
};
std::vector<std::string> strings(hid_t object,const char* name) {
    Handle attribute(H5Aopen(object,name,H5P_DEFAULT),H5Aclose);
    Handle type(H5Aget_type(attribute),H5Tclose);
    Handle space(H5Aget_space(attribute),H5Sclose);
    auto count=H5Sget_simple_extent_npoints(space);
    require(count>=0 && count<=64 && (count==0 || H5Tget_class(type)==H5T_STRING),
            Status::invalid_model,"invalid HDF5 name attribute");
    std::vector<std::string> result;
    if(!count) return result;
    // Frozen Keras 2.2.x checkpoints use bounded fixed-width byte attributes.
    // H5Aread cannot apply a bounded vlen allocator, so reject that unrelated
    // representation before allowing HDF5 to allocate unbounded strings.
    require(H5Tis_variable_str(type)<=0,Status::unsupported,"variable-length HDF5 attributes are outside the legacy checkpoint profile");
    {
        auto width=H5Tget_size(type);
        require(width>0 && width<=1024,Status::invalid_model,"invalid HDF5 string width");
        std::vector<char> buffer(checked_mul(static_cast<std::size_t>(count),width));
        require(H5Aread(attribute,type,buffer.data())>=0,Status::invalid_model,"HDF5 name read failed");
        for(hssize_t i=0;i<count;++i) {
            auto begin=buffer.begin()+i*static_cast<std::ptrdiff_t>(width);
            auto end=std::find(begin,begin+static_cast<std::ptrdiff_t>(width),'\0');
            result.emplace_back(begin,end);
        }
    }
    return result;
}
Tensor read_tensor(hid_t group,const std::string& name,const Limits& limits,std::size_t& total) {
    Handle dataset(H5Dopen2(group,name.c_str(),H5P_DEFAULT),H5Dclose);
    Handle space(H5Dget_space(dataset),H5Sclose);
    Handle type(H5Dget_type(dataset),H5Tclose);
    int rank=H5Sget_simple_extent_ndims(space);
    require(rank>=1 && rank<=2 && H5Tget_class(type)==H5T_FLOAT &&
            (H5Tget_size(type)==2 || H5Tget_size(type)==4),Status::invalid_model,"unsupported HDF5 weight type");
    hsize_t dims[2]={}; H5Sget_simple_extent_dims(space,dims,nullptr);
    Tensor tensor; std::size_t elements=1;
    for(int i=0;i<rank;++i) {
        require(dims[i]>0 && dims[i]<=65536,Status::invalid_model,"invalid HDF5 weight dimension");
        elements=checked_mul(elements,static_cast<std::size_t>(dims[i]));
        tensor.shape.push_back(static_cast<std::uint32_t>(dims[i]));
    }
    total=checked_add(total,checked_mul(elements,4));
    require(total<=limits.max_model_bytes,Status::resource_limit,"HDF5 weights exceed model limit");
    tensor.data.resize(elements);
    require(H5Dread(dataset,H5T_NATIVE_FLOAT,H5S_ALL,H5S_ALL,H5P_DEFAULT,tensor.data.data())>=0,
            Status::invalid_model,"HDF5 weight conversion failed");
    return tensor;
}
}
Model Model::from_hdf5(const std::string& path,const std::string& name,const Limits& limits) {
    Handle file(H5Fopen(path.c_str(),H5F_ACC_RDONLY,H5P_DEFAULT),H5Fclose);
    // Both weights-only files and complete Keras model files are supported.
    bool nested=H5Aexists(file,"layer_names")<=0;
    Handle root(H5Gopen2(file,nested?"model_weights":"/",H5P_DEFAULT),H5Gclose);
    auto layer_names=strings(root,"layer_names");
    std::vector<std::vector<Tensor>> tensors;
    std::size_t total=0;
    for(const auto& layer_name:layer_names) {
        Handle group(H5Gopen2(root,layer_name.c_str(),H5P_DEFAULT),H5Gclose);
        auto weight_names=strings(group,"weight_names");
        std::vector<Tensor> weights;
        for(const auto& weight_name:weight_names) weights.push_back(read_tensor(group,weight_name,limits,total));
        tensors.push_back(std::move(weights));
    }
    require(!tensors.empty() && !tensors[0].empty() && tensors[0][0].shape.size()==2,
            Status::invalid_model,"missing HDF5 embedding weights");
    auto layers=profile_layers(name,tensors[0][0].shape[0]);
    require(layers.size()==tensors.size(),Status::invalid_model,"HDF5 layer count differs from source constructor");
    for(std::size_t i=0;i<layers.size();++i) {
        require(layers[i].tensors.size()==tensors[i].size(),Status::invalid_model,"HDF5 weight count mismatch");
        layers[i].tensors=std::move(tensors[i]);
    }
    return load(serialize_model(name,layers),limits);
}
}  // namespace deepzip
