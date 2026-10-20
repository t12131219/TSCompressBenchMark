#include "native_bridge.hpp"
#include <fstream>
#include <vector>
#include <iterator>
#include <iostream>
#include <cstring>
int64_t lzbench_huff0_compress(char*,size_t,char*,size_t,size_t,size_t,void*);
int64_t lzbench_huff0_decompress(char*,size_t,char*,size_t,size_t,size_t,void*);
int main(int argc,char**argv){
 if(argc!=10){std::cerr<<"oracle enc|dec bits fire huffman path dims input output expected_bytes\n";return 2;}
 int bits=std::stoi(argv[2]),fire=std::stoi(argv[3]),h=std::stoi(argv[4]),path=std::stoi(argv[5]),d=std::stoi(argv[6]);
 std::ifstream f(argv[7],std::ios::binary);if(!f)return 3;
 std::vector<char> in((std::istreambuf_iterator<char>(f)),{});size_t n=in.size();in.resize(n+65536);
 std::vector<char> out(1024*1024),tmp(out.size());int64_t ret;
 if(std::string(argv[1]).rfind("enc",0)==0){
  ret=native_encode(bits,fire,path,in.data(),n/(bits/8),out.data(),d)*(bits/8);
  if(h){if(bits==16)ret++; ret=lzbench_huff0_compress(out.data(),ret,tmp.data(),tmp.size(),0,0,nullptr);out.swap(tmp);}
 }else{
  char* data=in.data();if(h){lzbench_huff0_decompress(in.data(),n,tmp.data(),tmp.size(),0,0,nullptr);data=tmp.data();}
  ret=native_decode(bits,fire,path,data,out.data())*(bits/8);
 }
 std::cout<<"{\"native_reported_bytes\":"<<ret<<"}\n";
 if(ret<0||ret>(int64_t)out.size())return 4;
 // enc16plus supplies the byte that the upstream length fails to count.
 if(std::string(argv[1])=="enc16plus"&&bits==16&&!h)ret++;
 std::ofstream o(argv[8],std::ios::binary);o.write(out.data(),ret);return !o;
}
