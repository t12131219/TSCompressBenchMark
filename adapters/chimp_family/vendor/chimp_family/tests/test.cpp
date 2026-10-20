// SPDX-License-Identifier: LicenseRef-Local-Research
#include "chimp_family.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cfenv>
#include <cstring>
#include <future>
#include <iostream>
#include <random>
using namespace chimp;
void check(bool b){if(!b)throw std::runtime_error("test assertion");}
template<class F>void fails(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}check(caught);}
std::uint64_t canon(std::uint64_t w){return (w&0x7ff0000000000000ULL)==0x7ff0000000000000ULL&&(w&0xfffffffffffffULL)?0x7ff8000000000000ULL:w;}
void lossless(){check(Fpc::to_long({1,2,3})==0x030201);check(Fpc::to_byte_array(0x010203)==std::vector<std::uint8_t>({3,2,1}));fails([&]{Fpc::to_long(std::vector<std::uint8_t>(9));});std::mt19937_64 rng(0xc12ab);for(unsigned method=1;method<=6;++method)for(unsigned n:{1U,4U,32U,128U,1024U}){Config c{Method(method),n,0.1f};for(std::size_t count:{0U,1U,2U,7U,511U,512U,513U,999U,1000U,1001U}){std::vector<std::uint64_t> a;for(std::size_t i=0;i<count;++i){auto w=i%3?rng():0;if(method==2||method==5)w&=0xffffffffULL;if(w==0x7ff8000000000000ULL||w==0x7fc00000ULL)w=0;a.push_back(w);}auto original=a;std::vector<std::uint8_t> raw;auto expected=a;
 if(method==6){Fpc e,d;raw=e.encode(a);for(auto& x:expected)x=canon(x);check(d.decode(raw,count)==expected);check(raw.size()<=raw_bound(c,count));e.finalize();e.finalize();fails([&]{e.encode({1});});e.reset();check(e.encode(a)==raw);}
 else{ChimpEncoder e(c);for(auto v:a)e.add(v);auto bits=e.finalize();check(bits.bytes==e.finalize().bytes);raw=bits.bytes;check(bits.meaningful_bits<=8*raw.size()&&8*raw.size()-bits.meaningful_bits<8);check(raw==encode_chimp(c,a).bytes);check(decode_chimp(c,raw)==a);ChimpDecoder decoder(c,raw);for(auto v:a){std::uint64_t got=0;check(decoder.next(got)&&got==v);}std::uint64_t unchanged=87;check(!decoder.next(unchanged)&&unchanged==87);check(!decoder.next(unchanged));decoder.reset(raw);for(auto v:a){std::uint64_t got=0;check(decoder.next(got)&&got==v);}check(raw.size()<=raw_bound(c,count));fails([&]{e.add(0);});e.reset();for(auto v:a)e.add(v);check(e.finalize().bytes==raw);}
 auto frame=encode_frame(c,a);check(decode_frame(frame).words==expected);check(a==original);
 if(count<=7){for(std::size_t k=0;k<frame.size();++k){auto bad=frame;bad.resize(k);fails([&]{decode_frame(bad);});}for(std::size_t k=0;k<frame.size();++k){auto bad=frame;bad[k]^=1;fails([&]{decode_frame(bad);});}auto extra=frame;extra.push_back(0);fails([&]{decode_frame(extra);});}
 }}
 // IEEE admitted domain and source canonicalization.
 std::vector<std::uint64_t> special={0,0x8000000000000000ULL,1,0xfffffffffffffULL,0x7ff0000000000000ULL,0xfff0000000000000ULL,0x7ff8000000000001ULL,0xfff123456789abcdULL};
 for(Method m:{Method::Chimp,Method::ChimpN,Method::ChimpNoIndex}){Config c{m,128,0};check(decode_chimp(c,encode_chimp(c,special).bytes)==special);fails([&]{encode_chimp(c,{0x7ff8000000000000ULL});});}
 Fpc f;fails([&]{f.encode(special,true);});Fpc clean;check(f.encode({42})==clean.encode({42}));
 for(std::size_t split:{1U,2U,3U,7U}){Fpc e,d;std::vector<std::uint64_t> a(31);for(auto& x:a)x=rng();for(std::size_t i=0;i<a.size();i+=split){std::vector<std::uint64_t> part(a.begin()+std::ptrdiff_t(i),a.begin()+std::ptrdiff_t(std::min(i+split,a.size())));auto raw=e.encode(part);fails([&]{auto bad=raw;bad.pop_back();d.decode(bad,part.size());});check(d.decode(raw,part.size())==part);}}
 for(Method m:{Method::ChimpN,Method::ChimpN32}){Config c{m,65536,0};std::vector<std::uint64_t> small={1,2,3};check(decode_chimp(c,encode_chimp(c,small).bytes)==small);}fails([&]{raw_bound({Method::ChimpN,65537,0},10);});fails([&]{raw_bound({Method::ChimpN,3,0},10);});fails([&]{raw_bound({Method::ChimpN,0,0},10);});fails([&]{raw_bound({Method::Chimp,128,0},max_values+1);});fails([&]{encode_chimp({Method::Chimp32,128,0},{0x100000000ULL});});
}
void lossies(){auto negative_zero=filter({Method::Pmc,128,0},{{0,-0.0f}});check(std::signbit(reconstruct(negative_zero,true)[0].value));auto old_round=std::fegetround();std::fesetround(FE_DOWNWARD);fails([&]{filter({Method::Pmc,128,.1f},{{0,0}});});std::fesetround(old_round);for(Method m:{Method::Pmc,Method::Swing,Method::Disjoint,Method::Quantized,Method::QuantizedFilter2}){Config c{m,128,0.1f};std::vector<Point> p;for(int i=0;i<1000;++i)p.push_back({i,float(std::sin(i*.03))});auto original=p;auto s=filter(c,p);auto decoded=reconstruct(s);SegmentDecoder sd(s);for(auto pt:decoded){Point got{};check(sd.next(got));check(got.timestamp==pt.timestamp&&((std::isnan(got.value)&&std::isnan(pt.value))||got.value==pt.value));}Point done{};check(!sd.next(done));sd.reset();check(sd.next(done));auto raw=serialize_segments(s);check(serialize_segments(parse_segments(raw))==raw);auto framed=encode_frame(c,p);auto d=decode_frame(framed);check(serialize_segments(d.segments)==raw);check(decoded.size()==1000);for(std::size_t i=0;i<p.size();++i)check(p[i].timestamp==original[i].timestamp&&p[i].value==original[i].value);auto q=quality(p,decoded,c.epsilon,m==Method::Quantized);check(q.violations<=p.size());for(std::size_t n:{0U,1U,2U}){std::vector<Point> tiny(p.begin(),p.begin()+std::ptrdiff_t(n));if((m!=Method::Pmc&&n==0)||(m==Method::Swing&&n==1))fails([&]{filter(c,tiny);});else check(!filter(c,tiny).empty()||m==Method::Pmc);}
 fails([&]{filter(c,{{1,0},{1,1}});});fails([&]{filter(c,{{1,std::numeric_limits<float>::infinity()}});});fails([&]{Config bad=c;bad.epsilon=-1;filter(bad,p);});}
 Config q{Method::Quantized,128,0.1f};auto s=filter(q,{{100,1}});auto decoded=reconstruct(s);check(!std::isfinite(decoded[0].value));fails([&]{encode_frame(q,std::vector<Point>{{100,1}},true);});
 auto irregular=filter({Method::Pmc,128,1},{{-3,0},{3,0}});check(reconstruct(irregular).size()==7);
 fails([&]{reconstruct({{INT64_MIN,INT64_MAX,0,0,0,0,0}});});fails([&]{parse_segments(std::vector<std::uint8_t>(51));});
}
void fuzz(){std::mt19937_64 rng(71);for(unsigned i=0;i<15000;++i){std::vector<std::uint8_t> b(rng()%96);for(auto& x:b)x=std::uint8_t(rng());try{decode_frame(b);}catch(const std::exception&){}try{decode_chimp({Method(1+rng()%5),128,.1f},b);}catch(const std::exception&){}try{Fpc f;f.decode(b,rng()%20);}catch(const std::exception&){}try{parse_segments(b);}catch(const std::exception&){} }}
int main(int argc,char**){try{if(argc==1){lossless();lossies();fuzz();}std::vector<std::future<void>> jobs;for(int i=0;i<4;++i)jobs.push_back(std::async(std::launch::async,[]{for(unsigned m=1;m<=6;++m){std::vector<std::uint64_t> a(513,42);auto f=encode_frame({Method(m),128,.1f},a);check(decode_frame(f).words==a);}}));for(auto& j:jobs)j.get();std::cout<<(argc==1?"PASS lossless state/reset/finalize, IEEE, bounds, malformed, filters, quality rejection, 15000 fuzz iterations, independent concurrency\n":"PASS independent concurrency only\n");return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
