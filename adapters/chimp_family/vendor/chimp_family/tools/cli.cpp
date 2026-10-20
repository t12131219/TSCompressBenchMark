// SPDX-License-Identifier: LicenseRef-Local-Research
#include "chimp_family.hpp"
#include <iostream>
#include <fstream>
#include <cstring>
#include <string>
#include <iterator>
using namespace chimp;
namespace {
std::uint64_t take(const std::vector<std::uint8_t>& b,std::size_t& p,unsigned n){if(p>b.size()||n>b.size()-p)throw std::runtime_error("short input");std::uint64_t v=0;for(unsigned i=0;i<n;++i)v|=std::uint64_t(b[p++])<<(8*i);return v;}
void put(std::vector<std::uint8_t>& b,std::uint64_t v,unsigned n){for(unsigned i=0;i<n;++i){b.push_back(std::uint8_t(v));v>>=8;}}
std::vector<std::uint8_t> words_bytes(const std::vector<std::uint64_t>& words){std::vector<std::uint8_t> b;for(auto w:words)put(b,w,8);return b;}
std::vector<std::uint8_t> points_bytes(const std::vector<Point>& p){std::vector<std::uint8_t> b;for(auto x:p){put(b,std::uint64_t(x.timestamp),8);std::uint32_t v;std::memcpy(&v,&x.value,4);put(b,v,4);}return b;}
std::vector<std::uint64_t> read_words(const std::vector<std::uint8_t>& b){if(b.size()%8)throw std::invalid_argument("word alignment");std::vector<std::uint64_t> w;std::size_t p=0;while(p<b.size())w.push_back(take(b,p,8));return w;}
std::vector<Point> read_points(const std::vector<std::uint8_t>& b){if(b.size()%12)throw std::invalid_argument("point alignment");std::vector<Point> out;std::size_t p=0;while(p<b.size()){auto v=take(b,p,8);std::int64_t t;std::memcpy(&t,&v,8);auto raw=std::uint32_t(take(b,p,4));float f;std::memcpy(&f,&raw,4);out.push_back({t,f});}return out;}
std::vector<std::uint8_t> run(unsigned mode,Config c,std::size_t count,const std::vector<std::uint8_t>& b){bool loss=unsigned(c.method)>=7;
 if(mode==10)return words_bytes({Fpc::to_long(b)});
 if(mode==11){auto w=read_words(b);if(w.size()!=1)throw std::invalid_argument("one residual required");return Fpc::to_byte_array(w[0]);}
 if(mode==3)return loss?encode_frame(c,read_points(b)):encode_frame(c,read_words(b));
 if(mode==4){auto d=decode_frame(b);return unsigned(d.config.method)>=7?points_bytes(d.points):words_bytes(d.words);}
 if(mode==5){auto s=filter(c,read_points(b));return points_bytes(reconstruct(s,c.method==Method::Pmc));}
 if(mode==6)return encode_frame(c,read_points(b),true);
 if(mode==1){if(loss)return serialize_segments(filter(c,read_points(b)));if(c.method==Method::Fpc){Fpc f;return f.encode(read_words(b));}return encode_chimp(c,read_words(b)).bytes;}
 if(mode==2){if(loss)return points_bytes(reconstruct(parse_segments(b),c.method==Method::Pmc));if(c.method==Method::Fpc){Fpc f;return words_bytes(f.decode(b,count));}return words_bytes(decode_chimp(c,b));}
 throw std::invalid_argument("mode");}
std::uint32_t rd32(std::istream& s){unsigned char b[4];s.read(reinterpret_cast<char*>(b),4);if(!s)throw std::runtime_error("short protocol");return std::uint32_t(b[0])|(std::uint32_t(b[1])<<8)|(std::uint32_t(b[2])<<16)|(std::uint32_t(b[3])<<24);}
void wr32(std::ostream& s,std::uint32_t v){char b[4];for(unsigned i=0;i<4;++i)b[i]=char((v>>(8*i))&255U);s.write(b,4);}
void server(){Fpc stream_encoder,stream_decoder;while(std::cin.peek()!=EOF){unsigned mode=rd32(std::cin);Config c;c.method=Method(rd32(std::cin));c.history=rd32(std::cin);auto ep=rd32(std::cin);std::memcpy(&c.epsilon,&ep,4);auto count=rd32(std::cin),len=rd32(std::cin);if(len>52*max_values+36)throw std::length_error("protocol limit");std::vector<std::uint8_t> b(len);std::cin.read(reinterpret_cast<char*>(b.data()),len);if(!std::cin)throw std::runtime_error("short protocol payload");try{auto out=mode==7?stream_encoder.encode(read_words(b)):mode==8?words_bytes(stream_decoder.decode(b,count)):mode==9?(stream_encoder.reset(),stream_decoder.reset(),std::vector<std::uint8_t>{}):run(mode,c,count,b);wr32(std::cout,0);wr32(std::cout,std::uint32_t(out.size()));std::cout.write(reinterpret_cast<const char*>(out.data()),std::streamsize(out.size()));}catch(const std::exception& e){std::string msg=e.what();wr32(std::cout,1);wr32(std::cout,std::uint32_t(msg.size()));std::cout.write(msg.data(),std::streamsize(msg.size()));}std::cout.flush();}}
}
int main(int argc,char** argv){try{if(argc==2&&std::string(argv[1])=="server"){server();return 0;}if(argc!=8){std::cerr<<"usage: chimp_cli MODE METHOD N EPS COUNT INPUT OUTPUT\nMODE: 1 raw-encode, 2 raw-decode, 3 frame-encode, 4 frame-decode, 5 filter-decode, 6 strict-frame; METHOD: 1..11; words64 LE or (i64,f32) LE points\n";return 2;}Config c{Method(std::stoul(argv[2])),std::uint32_t(std::stoul(argv[3])),std::stof(argv[4])};std::ifstream in(argv[6],std::ios::binary);if(!in)throw std::runtime_error("open input");std::vector<std::uint8_t> b((std::istreambuf_iterator<char>(in)),{});auto out=run(unsigned(std::stoul(argv[1])),c,std::stoull(argv[5]),b);std::ofstream file(argv[7],std::ios::binary);file.write(reinterpret_cast<const char*>(out.data()),std::streamsize(out.size()));if(!file)throw std::runtime_error("write output");return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
