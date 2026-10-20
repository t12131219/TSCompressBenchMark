#include "sprintz_delta.h"
#include "sprintz_xff.h"
#include <vector>
#include <iostream>
int main(){std::vector<uint16_t>data(1024+4096,65535),out(data.size());std::vector<int16_t>packed(data.size()*3);auto n=compress_rowmajor_delta_rle_16b(data.data(),1024,packed.data(),16);QueryParams q{QueryTypes::REDUCE_SUM,true};auto m=query_rowmajor_delta_rle_16b(packed.data(),out.data(),q);std::cout<<n<<' '<<m<<'\n';return m!=1024;}
