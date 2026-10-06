#include "internal.hpp"
namespace deepzip {
Model Model::from_hdf5(const std::string&,const std::string&,const Limits&) {
    throw Error(Status::unsupported,"native HDF5 importer is disabled in this build");
}
}
