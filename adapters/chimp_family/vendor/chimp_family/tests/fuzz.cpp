// SPDX-License-Identifier: LicenseRef-Local-Research
#include "chimp_family.hpp"
#include <cstdint>
#include <vector>
#include <exception>
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data,std::size_t size){if(size>65536)return 0;std::vector<std::uint8_t> b(data,data+size);try{chimp::decode_frame(b);}catch(const std::exception&){}if(size){chimp::Config c{chimp::Method(1+data[0]%5),std::uint32_t(1U<<(data[0]%11)),.1f};try{chimp::decode_chimp(c,b);}catch(const std::exception&){}try{chimp::Fpc f;f.decode(b,data[0]);}catch(const std::exception&){}try{chimp::parse_segments(b);}catch(const std::exception&){} }return 0;}
