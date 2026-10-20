#include "sprintz_port.h"
#include <fstream>
#include <vector>
#include <iterator>
#include <iostream>
int main(int argc,char**argv){try{
 if(argc!=10){std::cerr<<"sprintz_cli enc|dec width predictor huffman path dims input output expected_bytes\n";return 2;}
 sz_config c{unsigned(std::stoul(argv[2])),unsigned(std::stoul(argv[3])),unsigned(std::stoul(argv[4])),unsigned(std::stoul(argv[5])),unsigned(std::stoul(argv[6]))};
 std::ifstream f(argv[7],std::ios::binary);if(!f)return 3;
 std::vector<char> in((std::istreambuf_iterator<char>(f)),{});size_t expected=std::stoull(argv[9]),bound=0,z=0;bool enc=std::string(argv[1])=="enc";
 if(!enc&&std::string(argv[1])!="dec")return 2;
 int rc=sz_bound(&c,enc?in.size():expected,&bound);if(rc)return rc+10;
 std::vector<char> out(enc?bound:expected+1);rc=enc?sz_encode(&c,in.data(),in.size(),out.data(),out.size(),&z):sz_decode(&c,in.data(),in.size(),expected,out.data(),out.size(),&z);
 if(rc){std::cerr<<"status="<<rc<<"\n";return rc+10;}
 std::ofstream o(argv[8],std::ios::binary);if(!o)return 3;o.write(out.data(),z);if(!o)return 3;std::cout<<"{\"bytes\":"<<z<<"}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 2;}}
