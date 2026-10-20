#pragma once
#include "native_alloc.hpp"
#include <cstdint>
// Explicit supported compiler extension for x86 packed scalar loads/stores.
#define SZ_ALIAS(T) typedef T sz_##T __attribute__((aligned(1),may_alias));
SZ_ALIAS(uint16_t) SZ_ALIAS(int16_t) SZ_ALIAS(uint32_t) SZ_ALIAS(int32_t) SZ_ALIAS(uint64_t) SZ_ALIAS(int64_t)
#undef SZ_ALIAS
inline void* sz_native_malloc(size_t n){return sz_mem::alloc(n,1,false);}

#include <cstring>
inline int32_t sz_mul_wrap32(int64_t a,int64_t b){
 uint32_t u=uint32_t(a)*uint32_t(b);int32_t s;std::memcpy(&s,&u,sizeof s);return s;
}

inline int64_t sz_extract_signed(int64_t x,unsigned shift,unsigned width){
 if(width==0)return 0;
 uint64_t u=uint64_t(x)<<shift;int64_t s;std::memcpy(&s,&u,sizeof s);return s>>(64-width);
}
