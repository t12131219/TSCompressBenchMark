// SPDX-License-Identifier: LicenseRef-Local-Research
#include "chimp_family.hpp"
#include <chrono>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <vector>
#include <sched.h>
int main(){using namespace chimp;using Clock=std::chrono::steady_clock;cpu_set_t set;CPU_ZERO(&set);int cpu=sched_getcpu();CPU_SET(cpu,&set);int pinned=sched_setaffinity(0,sizeof(set),&set);std::cout<<"{\"scope\":\"standalone owning-vector API, setup+encode and fresh-decode; synthetic sine, not source speed ranking\",\"cpu\":"<<cpu<<",\"affinity_success\":"<<(pinned==0?"true":"false")<<",\"warmups\":10,\"repetitions\":31,\"rows\":[";std::vector<Point> points;std::vector<std::uint64_t> f64,f32;for(int i=0;i<512;++i){double d=std::sin(i*.02);float f=float(d);std::uint64_t w;std::uint32_t v;std::memcpy(&w,&d,8);std::memcpy(&v,&f,4);f64.push_back(w);f32.push_back(v);points.push_back({i,f});}
 for(unsigned method=1;method<=11;++method){Config c{Method(method),128,.1f};std::vector<double> enc,dec;std::size_t bytes=0;std::uint64_t sink=0;for(int rep=-10;rep<31;++rep){auto begin=Clock::now();auto b=method>=7?encode_frame(c,points):encode_frame(c,(method==2||method==5)?f32:f64);auto mid=Clock::now();auto d=decode_frame(b);auto end=Clock::now();sink+=d.words.size()+d.points.size();bytes=b.size();if(rep>=0){enc.push_back(std::chrono::duration<double,std::nano>(mid-begin).count());dec.push_back(std::chrono::duration<double,std::nano>(end-mid).count());}}std::sort(enc.begin(),enc.end());std::sort(dec.begin(),dec.end());if(method>1)std::cout<<',';std::cout<<"{\"method\":"<<method<<",\"count\":512,\"final_bits\":"<<bytes*8<<",\"encode_median_ns\":"<<enc[15]<<",\"decode_median_ns\":"<<dec[15]<<",\"encode_min_ns\":"<<enc[0]<<",\"encode_max_ns\":"<<enc[30]<<",\"sink\":"<<sink<<'}';}std::cout<<"]}\n";}
