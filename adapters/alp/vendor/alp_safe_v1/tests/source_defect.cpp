// Deliberate source UB repro, compiled with original headers ONLY.
#include <cstring>
#include <iostream>
#include <limits>
#include "alp.hpp"
int main(int argc,char** argv) {
    const int test=argc>1?std::stoi(argv[1]):0;
    volatile int factor=test==0?10:1;
    if(test==0) std::cout<<alp::decoder<float>::decode_value(0,factor,10)<<'\n';
    if(test==1) {volatile float x=std::numeric_limits<float>::max();std::cout<<alp::encoder<float>::encode_value<false>(x,0,0)<<'\n';}
    if(test==2) {volatile double x=alp::ENCODING_UPPER_LIMIT;std::cout<<alp::encoder<double>::encode_value(x,0,0)<<'\n';}
    if(test==3) {volatile int64_t x=std::numeric_limits<int64_t>::max();std::cout<<alp::decoder<double>::decode_value(x,factor,1)<<'\n';}
}
