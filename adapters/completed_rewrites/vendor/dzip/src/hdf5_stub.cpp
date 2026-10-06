#include "dzip_nn.hpp"
#include <stdexcept>
namespace dzip {
Network Network::from_hdf5(const std::string&,ModelProfile,std::uint32_t) {
    throw std::invalid_argument("HDF5 importer is disabled in this build");
}
}
