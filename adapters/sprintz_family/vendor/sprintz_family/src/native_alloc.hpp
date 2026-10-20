#pragma once
#include <cstdlib>
#include <vector>
#include <new>
#include <cstdint>
#include <algorithm>
#include <limits>
namespace sz_mem {
inline thread_local std::vector<void*> live;
inline thread_local int64_t countdown=-1;
inline void* alloc(size_t n,size_t s,bool zero){
 if(countdown==0)throw std::bad_alloc();
 if(countdown>0)--countdown;
 if(s && n>(std::numeric_limits<size_t>::max()-64)/s)throw std::bad_alloc();
 // Native stripe/header code deliberately issues wide loads. Own and initialize
 // a real 64-byte suffix for each scratch allocation; not sanitizer suppression.
 (void)zero;void*p=std::calloc(n*s+64,1);
 if(!p)throw std::bad_alloc();
 try{live.push_back(p);}catch(...){std::free(p);throw;}return p;
}
inline void release(void*p){if(!p)return;auto i=std::find(live.begin(),live.end(),p);if(i!=live.end())live.erase(i);std::free(p);}
struct scope {~scope(){for(void*p:live)std::free(p);live.clear();}};
}
